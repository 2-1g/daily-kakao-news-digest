import unittest
from datetime import date, datetime, timedelta, timezone

from news_digest.auth import InMemoryTokenStore, OAuthManager, OAuthToken
from news_digest.kakao import DefiniteDeliveryError, KakaoClient
from news_digest.pipeline import DigestPipeline
from news_digest.state import DeliveryBlocked, DeliveryStatus, InMemoryEditionStore, StateConflict

NOW = datetime(2026, 7, 1, 23, 0, tzinfo=timezone.utc)
DAY = date(2026, 7, 2)

class Clock:
    def __init__(self): self.now = NOW
    def __call__(self): return self.now

class Refresher:
    def refresh(self, value): raise AssertionError("unexpected refresh")

class RuntimeHardeningTests(unittest.TestCase):
    def token_store(self):
        return InMemoryTokenStore(OAuthToken("a", "r", NOW + timedelta(hours=1),
                                             NOW + timedelta(days=3)))

    def test_stage_heartbeat_prevents_second_worker_during_fifteen_minute_send(self):
        store, clock, tokens = InMemoryEditionStore(), Clock(), self.token_store()
        class Transport:
            def send_self_message(inner, access_token, text):
                clock.now += timedelta(minutes=15)
                with self.assertRaises(StateConflict):
                    store.acquire(DAY, "worker-2", clock.now)
        app = DigestPipeline(store, OAuthManager(tokens, Refresher()),
                             KakaoClient(Transport()), clock)
        self.assertEqual("acknowledged", app.run("worker-1", ["one"]).status)

    def test_definite_rejection_is_durable_failed_not_unknown(self):
        store, tokens = InMemoryEditionStore(), self.token_store()
        class Transport:
            def send_self_message(self, access_token, text):
                raise DefiniteDeliveryError("rejected")
        app = DigestPipeline(store, OAuthManager(tokens, Refresher()),
                             KakaoClient(Transport()), lambda: NOW)
        self.assertEqual("terminal_delivery_failure", app.run("one", ["one"]).status)
        edition = store.get(DAY)
        self.assertEqual("failed", edition.terminal_status)
        self.assertEqual(DeliveryStatus.REJECTED, edition.deliveries[1].status)
        with self.assertRaises(DeliveryBlocked):
            app.run("one", ["one"])

    def test_token_marked_successful_only_after_kakao_accepts(self):
        tokens = self.token_store()
        manager = OAuthManager(tokens, Refresher())
        manager.valid_access_token(NOW)
        self.assertEqual(set(), tokens.successful)
        class Transport:
            def send_self_message(self, access_token, text): return None
        DigestPipeline(InMemoryEditionStore(), manager, KakaoClient(Transport()),
                       lambda: NOW).run("one", ["one"])
        self.assertEqual({"1"}, tokens.successful)

    def test_refresh_expiry_emits_structured_warning(self):
        events = []
        manager = OAuthManager(self.token_store(), Refresher(),
                               lambda event, **fields: events.append((event, fields)))
        manager.valid_access_token(NOW)
        self.assertEqual("oauth_refresh_expiry_warning", events[0][0])
        self.assertNotIn("access_token", events[0][1])

if __name__ == "__main__": unittest.main()
