import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from news_digest.auth import OAuthToken
from news_digest.cloud import (FirestoreEditionStore, SecretManagerTokenStore,
                               edition_from_dict, edition_to_dict,
                               token_from_json, token_to_json)
from news_digest.main import main
from news_digest.pipeline import RunResult
from news_digest.state import DeliveryStatus, Edition, StateConflict


NOW = datetime(2026, 7, 1, 23, 0, tzinfo=timezone.utc)
DAY = date(2026, 7, 2)


class SecretClient:
    def __init__(self, token):
        self.versions = {"1": token_to_json(token)}
        self.aliases = {"active": 1}
        self.disabled = []

    def access_secret_version(self, request):
        requested = request["name"].rsplit("/", 1)[-1]
        version = str(self.aliases[requested]) if requested in self.aliases else requested
        return SimpleNamespace(name=request["name"].rsplit("/", 1)[0] + "/" + version,
                               payload=SimpleNamespace(data=self.versions[version]))

    def add_secret_version(self, request):
        version = str(len(self.versions) + 1)
        self.versions[version] = request["payload"]["data"]
        return SimpleNamespace(name=request["parent"] + "/versions/" + version)

    def get_secret(self, request):
        return SimpleNamespace(version_aliases=dict(self.aliases))

    def update_secret(self, request):
        self.aliases = dict(request["secret"].version_aliases)

    def disable_secret_version(self, request):
        self.disabled.append(request["name"].rsplit("/", 1)[-1])


class Document:
    def __init__(self):
        self.value = None
        self.generation = 0

    def get(self):
        return SimpleNamespace(exists=self.value is not None,
                               to_dict=lambda: self.value)

    def set(self, value):
        # Simulate the serialization boundary rather than retaining object aliases.
        self.value = json.loads(json.dumps(value))
        self.generation += 1


class FirestoreClient:
    def __init__(self):
        self.documents = {}

    def collection(self, name):
        client = self

        class Collection:
            def document(self, key):
                return client.documents.setdefault((name, key), Document())
        return Collection()


class AtomicRunner:
    """Injected stand-in for a Firestore transaction with generation checks."""

    def __init__(self):
        self.calls = 0

    def __call__(self, document, run_date, mutation, adapter):
        self.calls += 1
        observed = document.generation
        local = __import__("news_digest.state", fromlist=["InMemoryEditionStore"]).InMemoryEditionStore()
        snapshot = document.get()
        if snapshot.exists:
            local._editions[run_date] = edition_from_dict(snapshot.to_dict())
        result = mutation(local)
        if document.generation != observed:
            raise StateConflict("stale transaction rejected")
        document.set(edition_to_dict(local._editions[run_date]))
        adapter._editions[run_date] = local._editions[run_date]
        return result


class CloudPersistenceTests(unittest.TestCase):
    def test_token_serialization_round_trip_preserves_expiry_and_unicode_safe_bytes(self):
        original = OAuthToken("access", "refresh", NOW, NOW + timedelta(days=30))
        self.assertEqual(original, token_from_json(token_to_json(original)))

    def test_secret_manager_version_create_pointer_switch_read_and_retire(self):
        old = OAuthToken("a1", "r1", NOW, NOW + timedelta(days=30))
        new = OAuthToken("a2", "r2", NOW + timedelta(hours=1), NOW + timedelta(days=31))
        client = SecretClient(old)
        store = SecretManagerTokenStore("project", "token", client=client)
        self.assertEqual("1", store.active_version())
        version = store.create(new)
        store.verify(version)
        self.assertTrue(store.compare_and_set_active("1", version))
        self.assertEqual(new, store.read(store.active_version()))
        store.retire("1")
        self.assertEqual(["1"], client.disabled)

    def test_secret_pointer_compare_and_set_rejects_stale_expected_version(self):
        old = OAuthToken("a1", "r1", NOW)
        client = SecretClient(old)
        store = SecretManagerTokenStore("project", "token", client=client)
        version = store.create(OAuthToken("a2", "r2", NOW))
        self.assertFalse(store.compare_and_set_active("stale", version))
        self.assertEqual("1", store.active_version())

    def test_edition_serialization_round_trip_preserves_frozen_delivery_state(self):
        store = FirestoreEditionStore("project", client=FirestoreClient(),
                                      transaction_runner=AtomicRunner())
        store.acquire(DAY, "owner", NOW)
        store.freeze(DAY, "owner", ["one", "two"])
        store.begin(DAY, "owner", 1, NOW)
        store.resolve(DAY, "owner", 1, DeliveryStatus.UNKNOWN, NOW)
        store.reconcile_unknown_as_acknowledged(DAY, 1, NOW, "operator saw message")
        recovered = edition_from_dict(edition_to_dict(store.get(DAY)))
        self.assertEqual(store.get(DAY), recovered)
        self.assertEqual("operator saw message", recovered.deliveries[1].reconciliation_reason)

    def test_firestore_second_process_recovers_document_and_enforces_lease(self):
        client = FirestoreClient()
        runner = AtomicRunner()
        first = FirestoreEditionStore("project", client=client, transaction_runner=runner)
        first.acquire(DAY, "one", NOW)
        first.freeze(DAY, "one", ["message"])
        first.begin(DAY, "one", 1, NOW)
        second = FirestoreEditionStore("project", client=client, transaction_runner=runner)
        with self.assertRaises(StateConflict):
            second.acquire(DAY, "two", NOW + timedelta(hours=1))
        self.assertEqual(1, second.recover_stale_pending(DAY, NOW + timedelta(minutes=6)))
        self.assertEqual("unknown", client.documents[("news_digest_editions", DAY.isoformat())]
                         .value["deliveries"]["1"]["status"])

    def test_two_firestore_contenders_commit_only_one_lease_owner(self):
        client, runner = FirestoreClient(), AtomicRunner()
        one = FirestoreEditionStore("project", client=client, transaction_runner=runner)
        two = FirestoreEditionStore("project", client=client, transaction_runner=runner)
        self.assertEqual("one", one.acquire(DAY, "one", NOW).lease_owner)
        with self.assertRaises(StateConflict):
            two.acquire(DAY, "two", NOW)
        persisted = client.documents[("news_digest_editions", DAY.isoformat())].value
        self.assertEqual("one", persisted["lease_owner"])
        self.assertEqual(2, runner.calls)

    def test_stale_firestore_transaction_is_rejected_before_set(self):
        client = FirestoreClient()
        base_runner = AtomicRunner()
        first = FirestoreEditionStore("project", client=client, transaction_runner=base_runner)
        first.acquire(DAY, "one", NOW)
        document = client.documents[("news_digest_editions", DAY.isoformat())]

        def stale_runner(doc, run_date, mutation, adapter):
            observed = doc.generation
            local = __import__("news_digest.state", fromlist=["InMemoryEditionStore"]).InMemoryEditionStore()
            local._editions[run_date] = edition_from_dict(doc.get().to_dict())
            result = mutation(local)
            # A concurrent transaction commits after this transaction's read.
            concurrent = dict(doc.value)
            concurrent["lease_expires_at"] = (NOW + timedelta(minutes=10)).isoformat()
            doc.set(concurrent)
            if doc.generation != observed:
                raise StateConflict("stale transaction rejected")
            doc.set(edition_to_dict(local._editions[run_date]))
            return result

        stale = FirestoreEditionStore("project", client=client, transaction_runner=stale_runner)
        with self.assertRaisesRegex(StateConflict, "stale transaction"):
            stale.heartbeat(DAY, "one", NOW)
        self.assertEqual((NOW + timedelta(minutes=10)).isoformat(),
                         document.value["lease_expires_at"])

    def test_secret_alias_stale_generation_is_rejected_and_prior_is_preserved(self):
        old = OAuthToken("a1", "r1", NOW)
        client = SecretClient(old)
        state = {"active": "1", "generation": 1}

        def alias_cas(expected, new):
            if state["active"] != expected:
                return False
            state["active"] = new
            state["generation"] += 1
            return True

        first = SecretManagerTokenStore("project", "token", client=client,
                                        alias_cas=alias_cas)
        second = SecretManagerTokenStore("project", "token", client=client,
                                         alias_cas=alias_cas)
        candidate_one = first.create(OAuthToken("a2", "r2", NOW))
        candidate_two = second.create(OAuthToken("a3", "r3", NOW))
        self.assertTrue(first.compare_and_set_active("1", candidate_one))
        self.assertFalse(second.compare_and_set_active("1", candidate_two))
        self.assertEqual(candidate_one, state["active"])
        self.assertIn("1", client.versions)
        self.assertNotIn("1", client.disabled)

    def test_google_secret_alias_update_requires_and_carries_etag_precondition(self):
        class GoogleSecretClient(SecretClient):
            __module__ = "google.cloud.secretmanager"

            def __init__(self, token, etag):
                super().__init__(token)
                self.etag = etag
                self.updated_etag = None

            def get_secret(self, request):
                return SimpleNamespace(version_aliases=dict(self.aliases), etag=self.etag)

            def update_secret(self, request):
                self.updated_etag = request["secret"].etag
                super().update_secret(request)

        old = OAuthToken("a1", "r1", NOW)
        missing = SecretManagerTokenStore("project", "token",
                                          client=GoogleSecretClient(old, ""))
        with self.assertRaisesRegex(RuntimeError, "etag"):
            missing.compare_and_set_active("1", "2")
        guarded_client = GoogleSecretClient(old, "generation-7")
        guarded = SecretManagerTokenStore("project", "token", client=guarded_client)
        self.assertTrue(guarded.compare_and_set_active("1", "2"))
        self.assertEqual("generation-7", guarded_client.updated_etag)


class CloudCliTests(unittest.TestCase):
    def _run(self, argv, live_env=None):
        calls = []

        class Pipeline:
            def __init__(self, store, oauth, kakao, clock):
                calls.append(("init", store, oauth, kakao))

            def run(self, owner, messages, dry_run=False):
                calls.append(("run", owner, list(messages), dry_run))
                return RunResult("dry_run" if dry_run else "acknowledged", 0, "hash")

        env = {"GOOGLE_CLOUD_PROJECT": "project", "KAKAO_TOKEN_SECRET": "token",
               "KAKAO_CLIENT_ID": "client"}
        if live_env is not None:
            env["NEWS_DIGEST_LIVE_SEND"] = live_env
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "messages.json")
            path.write_text(json.dumps(["one", "two"]), encoding="utf-8")
            output = io.StringIO()
            with patch.dict(os.environ, env, clear=True), \
                 patch("news_digest.main.FirestoreEditionStore", return_value="store"), \
                 patch("news_digest.main.SecretManagerTokenStore", return_value="tokens"), \
                 patch("news_digest.main.OAuthManager", return_value="oauth"), \
                 patch("news_digest.main.KakaoClient", return_value="kakao"), \
                 patch("news_digest.main.DigestPipeline", Pipeline), redirect_stdout(output):
                code = main(argv + ["--messages", str(path)])
        return code, calls, json.loads(output.getvalue())

    def test_cloud_run_command_is_dry_run_by_default_and_never_sends(self):
        code, calls, output = self._run(["run"])
        self.assertEqual(0, code)
        self.assertTrue(calls[-1][3])
        self.assertEqual("dry_run", output["status"])

    def test_live_send_requires_exact_explicit_true_opt_in(self):
        for value, expected_dry_run in (("false", True), ("1", True), ("TRUE", False)):
            with self.subTest(value=value):
                code, calls, _ = self._run(["run"], value)
                self.assertEqual(0, code)
                self.assertEqual(expected_dry_run, calls[-1][3])

    def test_dry_run_flag_overrides_live_environment(self):
        _, calls, output = self._run(["run", "--dry-run"], "true")
        self.assertTrue(calls[-1][3])
        self.assertEqual("dry_run", output["status"])

    def test_cloud_run_manifest_command_matches_cli_parser(self):
        manifest = (Path(__file__).resolve().parents[1] / "infra/cloudrun-job.yaml").read_text(
            encoding="utf-8")
        self.assertIn('args: ["run"]', manifest)
        # Parser accepts exactly the command deployed by the manifest.
        code, _, _ = self._run(["run"])
        self.assertEqual(0, code)


if __name__ == "__main__":
    unittest.main()
