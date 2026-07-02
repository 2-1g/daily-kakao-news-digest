import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from news_digest.config import ComplianceError, ComplianceRegistry


def registry(data):
    handle = tempfile.NamedTemporaryFile("w", delete=False)
    json.dump({"sources": data}, handle); handle.close()
    return ComplianceRegistry.from_path(Path(handle.name))


def policy(**overrides):
    base = {"id":"x", "owner":"Owner", "mechanism":"api", "approved":True,
            "permitted_fields":["title"], "attribution_rule":"Link owner", "retention_days":0,
            "terms_url":"https://example.test/terms", "reviewed_on":"2026-01-01", "expires_on":"2026-12-31"}
    base.update(overrides); return base


class ComplianceTests(unittest.TestCase):
    def test_registry_finds_only_approved_policies_expiring_on_lead_date(self):
        candidate = registry([
            policy(id="later", expires_on="2026-08-02"),
            policy(id="due", expires_on="2026-08-01"),
            policy(id="disabled", approved=False, expires_on="2026-08-01"),
        ])
        self.assertEqual(
            ["due"],
            [item.source_id for item in candidate.expiring_in(date(2026, 7, 25), 7)],
        )

    def test_repository_registry_approval_is_short_lived(self):
        path = Path(__file__).parents[1] / "config" / "sources.yaml"
        loaded = ComplianceRegistry.from_path(path)
        loaded.require("naver-news", date(2026, 7, 1), ["title"])
        with self.assertRaises(ComplianceError):
            loaded.require("naver-news", date(2026, 8, 2), ["title"])

    def test_unknown_unapproved_expired_and_disallowed_fail_closed(self):
        cases = [
            (registry([policy()]), "missing", date(2026, 7, 1), ["title"]),
            (registry([policy(approved=False)]), "x", date(2026, 7, 1), ["title"]),
            (registry([policy(expires_on="2026-01-02")]), "x", date(2026, 7, 1), ["title"]),
            (registry([policy()]), "x", date(2026, 7, 1), ["body"]),
        ]
        for candidate, source, today, fields in cases:
            with self.subTest(source=source, fields=fields), self.assertRaises(ComplianceError):
                candidate.require(source, today, fields)

    def test_incomplete_entry_rejected_at_load(self):
        broken = policy(); broken["expires_on"] = None
        with self.assertRaises(ComplianceError): registry([broken])
