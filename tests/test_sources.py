import json
import unittest
from datetime import date

from news_digest.config import ComplianceRegistry, SourcePolicy
from news_digest.models import SourceMechanism
from news_digest.sources.base import HttpResponse
from news_digest.sources.gdelt import GdeltAdapter
from news_digest.sources.naver import NaverAdapter
from news_digest.sources.rss import RssAdapter


class FakeHttp:
    def __init__(self, body): self.body, self.calls = body, []
    def get(self, url, headers):
        self.calls.append((url, headers)); return HttpResponse(200, self.body, {})


def registry(source_id, mechanism, fields):
    p = SourcePolicy(source_id, "Owner", mechanism, True, frozenset(fields), "attribute", 0,
                     "https://example.test/terms", date(2026,1,1), date(2026,12,31))
    return ComplianceRegistry({source_id:p})


class SourceTests(unittest.TestCase):
    def test_naver_parses_metadata_without_article_fetch(self):
        body = json.dumps({"items":[{"title":"<b>시장</b>", "originallink":"https://news.test/a",
            "link":"https://naver.test/a", "description":"요약", "pubDate":"Wed, 01 Jul 2026 08:00:00 +0900"}]}).encode()
        http = FakeHttp(body)
        adapter = NaverAdapter(registry("naver-news", SourceMechanism.API, NaverAdapter.requested_fields), http, "id", "secret", "경제")
        article = adapter.collect(date(2026,7,1))[0]
        self.assertEqual((article.title, article.publisher, article.snippet), ("시장", "news.test", "요약"))
        self.assertEqual(len(http.calls), 1)

    def test_rss_and_atom_metadata(self):
        body = b"<rss><channel><item><title>Policy</title><link>https://publisher.test/x</link><description>Snippet</description><pubDate>Wed, 01 Jul 2026 00:00:00 GMT</pubDate></item></channel></rss>"
        fields = RssAdapter.requested_fields
        article = RssAdapter(registry("publisher-rss", SourceMechanism.RSS, fields), FakeHttp(body), "publisher-rss", "https://publisher.test/rss", "Publisher").collect(date(2026,7,1))[0]
        self.assertEqual(article.url, "https://publisher.test/x")
        self.assertEqual(article.snippet, "Snippet")

    def test_gdelt_uses_publisher_url_as_record(self):
        body = json.dumps({"articles":[{"title":"Global", "url":"https://publisher.test/g", "domain":"publisher.test", "seendate":"20260701T010000Z", "language":"English", "sourcecountry":"US"}]}).encode()
        adapter = GdeltAdapter(registry("gdelt-doc", SourceMechanism.API, GdeltAdapter.requested_fields), FakeHttp(body), "markets")
        article = adapter.collect(date(2026,7,1))[0]
        self.assertEqual(article.url, "https://publisher.test/g")
        self.assertEqual(article.publisher, "publisher.test")

    def test_compliance_check_happens_before_http(self):
        http = FakeHttp(b"{}")
        p = SourcePolicy("gdelt-doc", "Owner", SourceMechanism.API, False,
            frozenset(GdeltAdapter.requested_fields), "attribute", 0, "https://example.test", date(2026,1,1), date(2026,12,31))
        with self.assertRaises(Exception): GdeltAdapter(ComplianceRegistry({"gdelt-doc":p}), http, "x").collect(date(2026,7,1))
        self.assertEqual(http.calls, [])


if __name__ == "__main__": unittest.main()
