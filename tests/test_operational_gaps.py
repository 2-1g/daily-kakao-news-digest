"""Regression tests for attended operations and synchronous model guardrails."""

import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from news_digest.auth import OAuthToken, kakao_authorization_url
from news_digest.http import KakaoOAuthCodeExchanger
from news_digest.main import main
from news_digest.model_summarizer import (
    BudgetedModelSummarizer,
    ModelBudgetExceeded,
    ModelPrice,
)
from news_digest.models import ArticleCandidate, EventCluster
from news_digest.operator import bootstrap_token, reconcile_delivery
from news_digest.state import DeliveryStatus, InMemoryEditionStore, StateConflict


NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)
DAY = date(2026, 7, 1)


def cluster(event_id="event", *, investment=False):
    article = ArticleCandidate(
        "fixture", "publisher.test", "정책 변화", "https://publisher.test/a",
        NOW, snippet="확인된 정책 변화", language="ko", region="domestic",
    )
    return EventCluster(event_id, (article,), ("publisher.test",), (),
                        "economy", "domestic", investment)


class RecordingModelClient:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.requests = []

    def complete_json(self, request):
        self.requests.append(request)
        return self.responses.pop(0)


class OAuthBootstrapTests(unittest.TestCase):
    def test_authorization_url_encodes_required_consent_parameters(self):
        url = kakao_authorization_url("client", "https://local.test/cb?a=1", "csrf state")
        parsed = urlparse(url)
        self.assertEqual(("https", "kauth.kakao.com", "/oauth/authorize"),
                         (parsed.scheme, parsed.netloc, parsed.path))
        self.assertEqual({"client_id": ["client"], "redirect_uri": ["https://local.test/cb?a=1"],
                          "response_type": ["code"], "scope": ["talk_message"],
                          "state": ["csrf state"]}, parse_qs(parsed.query))

    def test_code_exchange_posts_grant_and_builds_expiring_token(self):
        payload = json.dumps({"access_token": "access-secret", "refresh_token": "refresh-secret",
                              "expires_in": 3600, "refresh_token_expires_in": 86400}).encode()
        response = io.BytesIO(payload)
        response.__enter__ = lambda value: value  # type: ignore[attr-defined]
        response.__exit__ = lambda *args: None  # type: ignore[attr-defined]
        requests = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return payload

        def fake_urlopen(request, timeout):
            requests.append((request, timeout))
            return Response()

        with patch("news_digest.http.urlopen", fake_urlopen):
            token = KakaoOAuthCodeExchanger("client", "https://local/cb", "secret").exchange(" code ")
        fields = parse_qs(requests[0][0].data.decode())
        self.assertEqual(["authorization_code"], fields["grant_type"])
        self.assertEqual(["code"], fields["code"])
        self.assertEqual(["secret"], fields["client_secret"])
        self.assertEqual("access-secret", token.access_token)
        self.assertGreater(token.access_expires_at, datetime.now(timezone.utc))

    def test_bootstrap_stores_token_but_returns_only_non_secret_metadata(self):
        token = OAuthToken("access-secret", "refresh-secret", NOW + timedelta(hours=1))
        stored = []

        class Exchanger:
            def __init__(self, *args):
                pass

            def exchange(self, code):
                self.code = code
                return token

        class Store:
            def __init__(self, *args):
                pass

            def install_bootstrap_token(self, value, replace_active=False):
                stored.append((value, replace_active))
                return "7"

        with patch("news_digest.operator.KakaoOAuthCodeExchanger", Exchanger), \
             patch("news_digest.operator.SecretManagerTokenStore", Store):
            output = bootstrap_token("project", "kakao-token", "client", "https://local/cb",
                                     code="authorization-secret")
        self.assertEqual([(token, False)], stored)
        self.assertEqual({"status": "stored", "secret": "kakao-token", "version": "7"},
                         json.loads(output))
        for secret in ("access-secret", "refresh-secret", "authorization-secret"):
            self.assertNotIn(secret, output)


class ReconciliationTests(unittest.TestCase):
    def _store(self, status):
        store = InMemoryEditionStore()
        store.acquire(DAY, "owner", NOW)
        store.freeze(DAY, "owner", ["message"])
        store.begin(DAY, "owner", 1, NOW)
        if status != DeliveryStatus.PENDING:
            store.resolve(DAY, "owner", 1, status, NOW)
        return store

    def test_only_unknown_can_transition_and_reason_operator_are_audited(self):
        for status in (DeliveryStatus.PENDING, DeliveryStatus.ACKNOWLEDGED):
            with self.subTest(status=status):
                with self.assertRaises(StateConflict):
                    self._store(status).reconcile_unknown_as_acknowledged(
                        DAY, 1, NOW, "observed in self-chat", "alice")
        store = self._store(DeliveryStatus.UNKNOWN)
        store.reconcile_unknown_as_acknowledged(DAY, 1, NOW, " observed in self-chat ", " alice ")
        record = store.get(DAY).deliveries[1]
        self.assertEqual(DeliveryStatus.ACKNOWLEDGED, record.status)
        self.assertEqual("observed in self-chat", record.reconciliation_reason)
        self.assertEqual("alice", record.reconciliation_operator)

    def test_blank_reason_or_operator_does_not_mutate_unknown(self):
        for reason, operator in (("", "alice"), ("seen", "")):
            store = self._store(DeliveryStatus.UNKNOWN)
            with self.subTest(reason=reason, operator=operator), self.assertRaises(ValueError):
                store.reconcile_unknown_as_acknowledged(DAY, 1, NOW, reason, operator)
            self.assertEqual(DeliveryStatus.UNKNOWN, store.get(DAY).deliveries[1].status)

    def test_reconciliation_command_validates_inputs_and_emits_audit_metadata(self):
        calls = []

        class Store:
            def __init__(self, project):
                self.project = project

            def reconcile_unknown_as_acknowledged(self, *args):
                calls.append(args)

        with patch("news_digest.operator.FirestoreEditionStore", Store):
            output = json.loads(reconcile_delivery("project", "2026-07-01", 2, "seen", "alice"))
        self.assertEqual((DAY, 2), calls[0][:2])
        self.assertEqual(("seen", "alice"), calls[0][-2:])
        self.assertEqual({"status": "acknowledged", "edition_id": "2026-07-01",
                          "message_index": 2, "operator": "alice"}, output)
        for edition, index in (("not-a-date", 1), ("2026-07-01", 0)):
            with self.subTest(edition=edition, index=index), self.assertRaises(ValueError):
                reconcile_delivery("project", edition, index, "seen", "alice")


class ModelGuardTests(unittest.TestCase):
    prices = {"nano": ModelPrice(Decimal("1"), Decimal("1")),
              "mini": ModelPrice(Decimal("2"), Decimal("2"))}

    def test_run_ceiling_is_checked_before_any_network_call(self):
        client = RecordingModelClient()
        summarizer = BudgetedModelSummarizer(client, self.prices, "nano", "mini",
                                             max_run_usd=Decimal("0.000001"),
                                             max_request_usd=Decimal("1"))
        with self.assertRaisesRegex(ModelBudgetExceeded, "run exceeds"):
            summarizer.summarize_all([cluster("a"), cluster("b")])
        self.assertEqual([], client.requests)

    def test_request_and_output_token_caps_are_applied_before_call(self):
        client = RecordingModelClient()
        summarizer = BudgetedModelSummarizer(client, self.prices, "nano", "mini",
                                             max_run_usd=Decimal("1"),
                                             max_request_usd=Decimal("0.000001"),
                                             max_output_tokens=123)
        with self.assertRaisesRegex(ModelBudgetExceeded, "request exceeds"):
            summarizer.summarize_all([cluster()])
        self.assertEqual([], client.requests)
        self.assertEqual(123, summarizer._request(cluster()).max_output_tokens)

    def test_routes_investment_to_mini_and_general_to_nano(self):
        valid = json.dumps({"headline": "요약", "clauses": [
            {"text": "확인된 정책 변화", "evidence_ids": ["E1"], "analysis": False}]})
        client = RecordingModelClient([valid, valid])
        results = BudgetedModelSummarizer(client, self.prices, "nano", "mini",
                                          max_run_usd=Decimal("1"),
                                          max_request_usd=Decimal("1")).summarize_all(
                                              [cluster("general"), cluster("invest", investment=True)])
        self.assertEqual(["nano", "mini"], [request.model for request in client.requests])
        self.assertEqual(["요약", "요약"], [item.headline for item in results])

    def test_bad_grounding_or_client_failure_uses_deterministic_fallback(self):
        unsupported = json.dumps({"headline": "주장", "clauses": [
            {"text": "근거 없음", "evidence_ids": ["E404"], "analysis": False}]})

        class Client(RecordingModelClient):
            def complete_json(self, request):
                self.requests.append(request)
                if len(self.requests) == 2:
                    raise OSError("network unavailable")
                return unsupported

        client = Client()
        clusters = [cluster("bad-grounding"), cluster("network")]
        results = BudgetedModelSummarizer(client, self.prices, "nano", "mini",
                                          max_run_usd=Decimal("1"),
                                          max_request_usd=Decimal("1")).summarize_all(clusters)
        self.assertEqual([candidate.primary.title for candidate in clusters],
                         [item.headline for item in results])
        self.assertTrue(all(item.clauses[0].evidence_ids == ("E1",) for item in results))


class BudgetArtifactTests(unittest.TestCase):
    def test_budget_setup_has_three_async_alerts_and_no_automatic_shutdown(self):
        script = (Path(__file__).parents[1] / "infra" / "setup-budget.sh").read_text(
            encoding="utf-8")
        for threshold in ("0.50", "0.80", "1.00"):
            self.assertEqual(1, script.count("--threshold-rule=percent=" + threshold))
        self.assertIn("NOT a hard stop", script)
        self.assertIn("budget-suspension.md manually", script)
        for forbidden in ("scheduler jobs pause", "run jobs delete", "cloud run jobs delete"):
            self.assertNotIn(forbidden, script.lower())


if __name__ == "__main__":
    unittest.main()
