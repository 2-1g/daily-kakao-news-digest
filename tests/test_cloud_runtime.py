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

    def get(self):
        return SimpleNamespace(exists=self.value is not None,
                               to_dict=lambda: self.value)

    def set(self, value):
        # Simulate the serialization boundary rather than retaining object aliases.
        self.value = json.loads(json.dumps(value))


class FirestoreClient:
    def __init__(self):
        self.documents = {}

    def collection(self, name):
        client = self

        class Collection:
            def document(self, key):
                return client.documents.setdefault((name, key), Document())
        return Collection()


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
        edition = Edition(DAY, "owner", NOW + timedelta(minutes=5))
        store = FirestoreEditionStore("project", client=FirestoreClient())
        store._editions[DAY] = edition
        store.freeze(DAY, "owner", ["one", "two"])
        store.begin(DAY, "owner", 1, NOW)
        store.resolve(DAY, "owner", 1, DeliveryStatus.UNKNOWN, NOW)
        store.reconcile_unknown_as_acknowledged(DAY, 1, NOW, "operator saw message")
        recovered = edition_from_dict(edition_to_dict(store.get(DAY)))
        self.assertEqual(store.get(DAY), recovered)
        self.assertEqual("operator saw message", recovered.deliveries[1].reconciliation_reason)

    def test_firestore_second_process_recovers_document_and_enforces_lease(self):
        client = FirestoreClient()
        first = FirestoreEditionStore("project", client=client)
        first.acquire(DAY, "one", NOW)
        first.freeze(DAY, "one", ["message"])
        first.begin(DAY, "one", 1, NOW)
        second = FirestoreEditionStore("project", client=client)
        with self.assertRaises(StateConflict):
            second.acquire(DAY, "two", NOW + timedelta(hours=1))
        self.assertEqual(1, second.recover_stale_pending(DAY, NOW + timedelta(minutes=6)))
        self.assertEqual("unknown", client.documents[("news_digest_editions", DAY.isoformat())]
                         .value["deliveries"]["1"]["status"])


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
