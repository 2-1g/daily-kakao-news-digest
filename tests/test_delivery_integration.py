import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from news_digest.auth import (AuthenticationError, InMemoryTokenStore,
                              OAuthManager, OAuthToken,
                              ReauthorizationRequired)
from news_digest.kakao import (AmbiguousDeliveryError, DefiniteDeliveryError,
                               KakaoClient)
from news_digest.main import main
from news_digest.pipeline import DigestPipeline
from news_digest.state import (DeliveryBlocked, DeliveryStatus,
                               InMemoryEditionStore, StateConflict,
                               edition_hash)


NOW = datetime(2026, 7, 1, 23, 0, tzinfo=timezone.utc)  # 08:00 KST


def token(*, expired=False, refresh_expired=False, refresh="refresh"):
    return OAuthToken(
        "access", refresh,
        NOW - timedelta(seconds=1) if expired else NOW + timedelta(hours=1),
        NOW - timedelta(seconds=1) if refresh_expired else NOW + timedelta(days=30),
    )


class Refresher:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, 0

    def refresh(self, refresh_token):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class Transport:
    def __init__(self, outcomes=()):
        self.outcomes, self.sent = list(outcomes), []

    def send_self_message(self, access_token, text):
        self.sent.append(text)
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if outcome:
                raise outcome


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


def pipeline(store=None, transport=None, clock=None, oauth_store=None):
    store = store or InMemoryEditionStore()
    transport = transport or Transport()
    clock = clock or Clock()
    oauth_store = oauth_store or InMemoryTokenStore(token())
    manager = OAuthManager(oauth_store, Refresher(token()))
    return DigestPipeline(store, manager, KakaoClient(transport), clock), transport


class EditionStateIntegrationTests(unittest.TestCase):
    def test_edition_freeze_hash_and_order_are_immutable(self):
        store = InMemoryEditionStore()
        store.acquire(date(2026, 7, 2), "one", NOW)
        expected = edition_hash(["첫째", "둘째"])
        self.assertEqual(expected, store.freeze(date(2026, 7, 2), "one", ["첫째", "둘째"]))
        self.assertEqual(("첫째", "둘째"), store.get(date(2026, 7, 2)).messages)
        with self.assertRaises(StateConflict):
            store.freeze(date(2026, 7, 2), "one", ["둘째", "첫째"])

    def test_lease_overlap_and_stale_takeover_only_before_delivery(self):
        store = InMemoryEditionStore()
        day = date(2026, 7, 2)
        store.acquire(day, "one", NOW, timedelta(minutes=1))
        with self.assertRaises(StateConflict):
            store.acquire(day, "two", NOW + timedelta(seconds=30))
        self.assertEqual("two", store.acquire(day, "two", NOW + timedelta(minutes=2)).lease_owner)
        store.freeze(day, "two", ["message"])
        store.begin(day, "two", 1, NOW + timedelta(minutes=2))
        with self.assertRaises(StateConflict):
            store.acquire(day, "three", NOW + timedelta(hours=1))

    def test_stale_pending_is_promoted_to_unknown_and_blocks_resend(self):
        store = InMemoryEditionStore()
        day = date(2026, 7, 2)
        store.acquire(day, "one", NOW)
        store.freeze(day, "one", ["message"])
        store.begin(day, "one", 1, NOW)
        self.assertEqual(1, store.recover_stale_pending(day, NOW + timedelta(minutes=5)))
        self.assertEqual(DeliveryStatus.UNKNOWN, store.get(day).deliveries[1].status)
        with self.assertRaises(DeliveryBlocked):
            store.begin(day, "one", 1, NOW + timedelta(minutes=6))

    def test_manual_reconciliation_requires_unknown_and_audit_reason(self):
        store = InMemoryEditionStore()
        day = date(2026, 7, 2)
        store.acquire(day, "one", NOW)
        store.freeze(day, "one", ["message"])
        store.begin(day, "one", 1, NOW)
        store.resolve(day, "one", 1, DeliveryStatus.UNKNOWN, NOW)
        with self.assertRaises(ValueError):
            store.reconcile_unknown_as_acknowledged(day, 1, NOW, "  ")
        store.reconcile_unknown_as_acknowledged(day, 1, NOW + timedelta(minutes=1),
                                                "visually confirmed in self-chat")
        record = store.get(day).deliveries[1]
        self.assertEqual(DeliveryStatus.ACKNOWLEDGED, record.status)
        self.assertEqual("visually confirmed in self-chat", record.reconciliation_reason)
        with self.assertRaises(StateConflict):
            store.reconcile_unknown_as_acknowledged(day, 1, NOW, "duplicate attempt")

    def test_crash_after_kakao_acceptance_before_ack_persistence_never_resends(self):
        class CrashOnResolveStore(InMemoryEditionStore):
            crashed = False

            def resolve(self, *args, **kwargs):
                if not self.crashed:
                    self.crashed = True
                    raise RuntimeError("crash before ack persistence")
                return super().resolve(*args, **kwargs)

        store, transport, clock = CrashOnResolveStore(), Transport(), Clock()
        app, _ = pipeline(store, transport, clock)
        with self.assertRaises(RuntimeError):
            app.run("one", ["accepted by Kakao"])
        self.assertEqual(["accepted by Kakao"], transport.sent)
        clock.now += timedelta(minutes=6)
        with self.assertRaises(DeliveryBlocked):
            app.run("one", ["accepted by Kakao"])
        self.assertEqual(["accepted by Kakao"], transport.sent)
        self.assertEqual(DeliveryStatus.UNKNOWN,
                         store.get(date(2026, 7, 2)).deliveries[1].status)

    def test_ambiguous_failure_stops_continuation_and_rerun(self):
        store, transport = InMemoryEditionStore(), Transport([TimeoutError("timeout")])
        app, _ = pipeline(store, transport)
        result = app.run("one", ["one", "two"])
        self.assertEqual(("unknown", 0), (result.status, result.sent))
        self.assertEqual(["one"], transport.sent)
        with self.assertRaises(DeliveryBlocked):
            app.run("one", ["one", "two"])
        self.assertEqual(["one"], transport.sent)

    def test_definitive_and_ambiguous_failures_are_distinct(self):
        definite = KakaoClient(Transport([DefiniteDeliveryError("rejected")]))
        with self.assertRaises(DefiniteDeliveryError):
            definite.send("token", "text")
        ambiguous = KakaoClient(Transport([ConnectionResetError("lost ack")]))
        with self.assertRaises(AmbiguousDeliveryError):
            ambiguous.send("token", "text")

    def test_definitive_failure_does_not_enter_send_loop(self):
        store, transport = InMemoryEditionStore(), Transport([DefiniteDeliveryError("quota")])
        app, _ = pipeline(store, transport)
        self.assertEqual("terminal_delivery_failure", app.run("one", ["one", "two"]).status)
        self.assertEqual(["one"], transport.sent)
        with self.assertRaises(DeliveryBlocked):
            app.run("one", ["one", "two"])
        self.assertEqual(["one"], transport.sent)

    def test_acknowledged_rerun_sends_nothing(self):
        app, transport = pipeline()
        self.assertEqual("acknowledged", app.run("one", ["one", "two"]).status)
        self.assertEqual(0, app.run("one", ["one", "two"]).sent)
        self.assertEqual(["one", "two"], transport.sent)

    def test_missed_run_after_0900_kst_never_backfills(self):
        late = Clock(datetime(2026, 7, 2, 0, 1, tzinfo=timezone.utc))
        app, transport = pipeline(clock=late)
        self.assertEqual("missed", app.run("one", ["news"]).status)
        late.now += timedelta(minutes=30)
        self.assertEqual("missed", app.run("one", ["news"]).status)
        self.assertEqual([], transport.sent)

    def test_dry_run_cli_validates_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "messages.json")
            path.write_text(json.dumps(["하나", "둘"]), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, main(["--dry-run", "--messages", str(path)]))
            self.assertEqual({"status": "dry_run", "messages": 2, "characters": 3},
                             json.loads(output.getvalue()))


class OAuthRotationIntegrationTests(unittest.TestCase):
    def test_expired_access_refreshes_once_then_sends_in_order(self):
        store = InMemoryTokenStore(token(expired=True))
        refresher = Refresher(token(refresh="rotated"))
        transport = Transport()
        app = DigestPipeline(InMemoryEditionStore(), OAuthManager(store, refresher),
                             KakaoClient(transport), Clock())
        self.assertEqual("acknowledged", app.run("one", ["one", "two"]).status)
        self.assertEqual(1, refresher.calls)
        self.assertEqual(["one", "two"], transport.sent)

    def test_expired_refresh_requires_operator_reauthorization(self):
        store = InMemoryTokenStore(token(refresh_expired=True))
        with self.assertRaises(ReauthorizationRequired):
            OAuthManager(store, Refresher(token())).valid_access_token(NOW)

    def test_refresh_failure_is_safe_and_retains_prior(self):
        store = InMemoryTokenStore(token(expired=True))
        with self.assertRaises(AuthenticationError):
            OAuthManager(store, Refresher(error=OSError("redacted"))).valid_access_token(NOW)
        self.assertEqual("1", store.active_version())
        self.assertNotIn("1", store.retired)

    def test_refresh_rotation_switches_pointer_and_retains_prior(self):
        store = InMemoryTokenStore(token(expired=True))
        result = OAuthManager(store, Refresher(token(refresh="rotated"))).valid_access_token(NOW)
        self.assertEqual(("2", "1"), (result.active_version, result.previous_version))
        self.assertEqual("2", store.active_version())
        self.assertNotIn("2", store.successful)
        self.assertNotIn("1", store.retired)

    def test_rotation_crashes_at_each_phase_without_losing_last_usable_token(self):
        for phase in ("create", "verify", "compare_and_set_active"):
            with self.subTest(phase=phase):
                class CrashStore(InMemoryTokenStore):
                    def __getattribute__(self, name):
                        attr = super().__getattribute__(name)
                        if name == phase and callable(attr):
                            def crash(*args, **kwargs):
                                raise RuntimeError("injected phase crash")
                            return crash
                        return attr

                store = CrashStore(token(expired=True))
                with self.assertRaises(RuntimeError):
                    OAuthManager(store, Refresher(token(refresh="new"))).valid_access_token(NOW)
                # Before pointer switch, prior remains active. After it, candidate is active,
                # but prior remains present for explicit rollback/grace recovery.
                self.assertIn(store.active_version(), store.versions)
                self.assertIn("1", store.versions)
                self.assertNotIn("1", store.retired)

    def test_success_marker_failure_after_acceptance_does_not_authorize_resend(self):
        class MarkerCrashStore(InMemoryTokenStore):
            def mark_successful_use(self, version):
                raise RuntimeError("marker unavailable")

        store = MarkerCrashStore(token())
        transport = Transport()
        app = DigestPipeline(InMemoryEditionStore(), OAuthManager(store, Refresher(token())),
                             KakaoClient(transport), Clock())
        with self.assertRaisesRegex(RuntimeError, "marker unavailable"):
            app.run("one", ["accepted"])
        # ACK persistence precedes the operational marker, so a retry is a no-op.
        self.assertEqual("acknowledged", app.run("one", ["accepted"]).status)
        self.assertEqual(["accepted"], transport.sent)

    def test_first_rejection_rolls_back_new_unproven_token_without_resend(self):
        store = InMemoryTokenStore(token(expired=True))
        transport = Transport([DefiniteDeliveryError("auth rejected")])
        app = DigestPipeline(InMemoryEditionStore(),
                             OAuthManager(store, Refresher(token(refresh="new"))),
                             KakaoClient(transport), Clock())
        result = app.run("one", ["first", "second"])
        self.assertEqual("terminal_delivery_failure", result.status)
        self.assertEqual("1", store.active_version())
        self.assertEqual("rolled_back", store.rotation_phases["2"][0])
        self.assertEqual(["first"], transport.sent)

    def test_rejection_does_not_rollback_already_proven_rotation(self):
        store = InMemoryTokenStore(token(expired=True))
        manager = OAuthManager(store, Refresher(token(refresh="new")))
        rotation = manager.valid_access_token(NOW)
        manager.mark_successful_use(rotation.active_version)
        self.assertFalse(manager.rollback_unproven(rotation))
        self.assertEqual("2", store.active_version())

    def test_restart_recovers_unproven_rotation_context_for_rollback(self):
        store = InMemoryTokenStore(token(expired=True))
        OAuthManager(store, Refresher(token(refresh="new"))).valid_access_token(NOW)
        restarted = OAuthManager(store, Refresher(error=AssertionError("no refresh")))
        recovered = restarted.valid_access_token(NOW)
        self.assertEqual("1", recovered.previous_version)
        self.assertTrue(restarted.rollback_unproven(recovered))
        self.assertEqual("1", store.active_version())


if __name__ == "__main__":
    unittest.main()
