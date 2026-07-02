import unittest
from datetime import date

from news_digest.config import ComplianceRegistry, SourcePolicy
from news_digest.main import source_expiry_reminder
from news_digest.models import SourceMechanism


def source(source_id, expires_on):
    return SourcePolicy(
        source_id, "Owner", SourceMechanism.API, True, frozenset({"title"}),
        "attribute", 0, "https://example.test/terms", date(2026, 7, 1), expires_on,
    )


class ExpiryReminderTests(unittest.TestCase):
    def test_reminder_is_emitted_exactly_seven_days_before_expiry(self):
        registry = ComplianceRegistry({
            "naver-news": source("naver-news", date(2026, 8, 1)),
            "gdelt-doc": source("gdelt-doc", date(2026, 8, 1)),
        })
        message = source_expiry_reminder(registry, date(2026, 7, 25))
        self.assertIn("D-7", message)
        self.assertIn("gdelt-doc, naver-news", message)
        self.assertIn("2026-08-01", message)
        self.assertLessEqual(len(message), 200)

    def test_reminder_is_absent_outside_lead_day(self):
        registry = ComplianceRegistry({
            "naver-news": source("naver-news", date(2026, 8, 1)),
        })
        self.assertEqual("", source_expiry_reminder(registry, date(2026, 7, 24)))


if __name__ == "__main__":
    unittest.main()
