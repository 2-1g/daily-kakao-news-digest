"""Boundary and property-style tests for deterministic editorial processing."""

import json
import unittest
from datetime import datetime, timedelta, timezone

from news_digest.compose import DISCLAIMER, DigestComposer
from news_digest.dedupe import cluster_articles
from news_digest.models import (
    ArticleCandidate,
    DigestItem,
    Evidence,
    EventCluster,
    GroundedClause,
)
from news_digest.normalize import normalize_url
from news_digest.rank import RankConfig, editorial_metrics, rank_clusters, score_cluster
from news_digest.summarize import deterministic_fallback, parse_synthesis, summarize


NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)


def article(title, publisher="alpha.kr", url=None, *, hours=1, region="domestic", **metadata):
    slug = abs(hash((title, publisher)))
    return ArticleCandidate(
        "fixture", publisher, title, url or f"https://{publisher}/news/{slug}",
        NOW - timedelta(hours=hours), snippet=f"{title}에 관한 확인된 설명입니다.",
        language="ko", region=region, metadata=metadata,
    )


def cluster(event_id, publisher, *, score="0.8", category="economy", region="domestic",
            investment=False, hours=1, independent=None):
    candidate = article(
        f"{event_id} 핵심 경제 정책 변화", publisher, hours=hours, region=region,
        impact=score, category=category,
        investment_relevance=str(investment).lower(),
    )
    return EventCluster(
        event_id, (candidate,), tuple(independent or (publisher,)), (), category, region, investment,
    )


def item(index, *, headline=None, fact=None, url=None):
    evidence = Evidence(
        "E1", fact or f"검증된 사실 {index}", f"source-{index}.kr",
        url or f"https://source-{index}.kr/a/{index}",
    )
    return DigestItem(
        str(index), headline or f"주요 뉴스 {index}",
        (GroundedClause(fact or f"검증된 사실 {index}", ("E1",)),), (evidence,),
        "economy", "domestic", index % 2 == 0,
    )


class UrlCanonicalizationTests(unittest.TestCase):
    def test_removes_tracking_fragment_default_port_and_sorts_query(self):
        url = "HTTPS://Example.COM:443/path/?utm_source=x&b=2&fbclid=z&a=1#part"
        self.assertEqual("https://example.com/path?a=1&b=2", normalize_url(url))

    def test_preserves_meaningful_blank_and_repeated_parameters(self):
        canonical = normalize_url("https://x.test/a?tag=b&empty=&tag=a")
        self.assertEqual("https://x.test/a?empty=&tag=a&tag=b", canonical)

    def test_is_idempotent_for_varied_urls(self):
        urls = (
            "http://EXAMPLE.com:80",
            "https://example.com/a///?z=9&utm_medium=m",
            "https://example.com/%ED%95%9C%EA%B8%80?q=%ED%95%9C%EA%B8%80",
        )
        for original in urls:
            with self.subTest(original=original):
                once = normalize_url(original)
                self.assertEqual(once, normalize_url(once))


class ClusteringTests(unittest.TestCase):
    def test_variant_headlines_cluster_but_unrelated_event_does_not(self):
        articles = (
            article("한국은행 기준금리 동결 결정", "a.kr"),
            article("한국은행 기준금리 동결 결정 속보", "b.kr"),
            article("국회 연금개혁 법안 본회의 통과", "c.kr"),
        )
        groups = cluster_articles(articles)
        self.assertEqual([1, 2], sorted(len(group.articles) for group in groups))

    def test_canonical_url_duplicate_is_removed(self):
        common = "https://a.kr/story?id=1"
        groups = cluster_articles((
            article("수출 증가 무역수지 개선", "a.kr", common + "&utm_source=x"),
            article("수출 증가 무역수지 개선", "a.kr", common),
        ))
        self.assertEqual(1, len(groups))
        self.assertEqual(1, len(groups[0].articles))

    def test_syndicated_publishers_do_not_count_as_independent_confirmation(self):
        groups = cluster_articles((
            article("정부 반도체 지원 정책 확대", "origin.kr", syndication_id="wire-1"),
            article("정부 반도체 지원 정책 확대", "copy.kr", syndication_id="wire-1"),
            article("정부 반도체 지원 정책 확대", "independent.kr"),
        ))
        self.assertEqual(1, len(groups))
        self.assertEqual(("copy.kr",), groups[0].syndicated_publishers)
        self.assertEqual(("independent.kr", "origin.kr"), groups[0].independent_publishers)

    def test_editorial_dimensions_are_deterministically_inferred(self):
        domestic = cluster_articles((article(
            "한국은행 기준금리 동결, 코스피 영향 주목", "a.kr", region=None,
        ),))[0]
        entertainment = cluster_articles((article(
            "해외 배우 신작 영화 공개", "b.com", region=None,
        ),))[0]
        self.assertEqual(("economy", "domestic", True),
                         (domestic.category, domestic.region, domestic.investment_relevance))
        self.assertEqual(("entertainment", "overseas", False),
                         (entertainment.category, entertainment.region,
                          entertainment.investment_relevance))


class RankingTests(unittest.TestCase):
    def test_independent_confirmation_raises_score(self):
        base = cluster("one", "a.kr", independent=("a.kr",))
        confirmed = EventCluster(
            "two", base.articles, ("a.kr", "b.kr", "c.kr"), (),
            base.category, base.region, base.investment_relevance,
        )
        self.assertGreater(score_cluster(confirmed, NOW), score_cluster(base, NOW))

    def test_publisher_concentration_cap_and_diversity(self):
        candidates = [cluster(f"a{i}", "one.kr", score="1") for i in range(5)]
        candidates += [cluster("b", "two.kr", score="0.9"), cluster("c", "three.kr", score="0.8")]
        selected = rank_clusters(candidates, NOW, RankConfig(minimum_score=0, max_items=6, max_publisher_share=.5))
        counts = {publisher: sum(c.primary.publisher == publisher for c in selected)
                  for publisher in {c.primary.publisher for c in selected}}
        self.assertLessEqual(max(counts.values()) / len(selected), .5)
        self.assertGreaterEqual(len(counts), 3)

    def test_soft_ratios_do_not_admit_below_threshold_filler(self):
        strong = cluster("strong", "a.kr", region="overseas", investment=False)
        filler = cluster("filler", "b.kr", score="0", category="sports",
                         region="domestic", investment=True, hours=100)
        selected = rank_clusters((strong, filler), NOW, RankConfig(minimum_score=.4))
        self.assertEqual((strong,), selected)

    def test_quiet_normal_and_major_days_adapt_without_padding(self):
        quiet = rank_clusters((cluster("q", "q.kr"),), NOW, RankConfig(minimum_score=0, max_items=10))
        normal = rank_clusters(
            tuple(cluster(f"n{i}", f"n{i}.kr") for i in range(5)), NOW,
            RankConfig(minimum_score=0, max_items=10),
        )
        major = rank_clusters(
            tuple(cluster(f"m{i}", f"m{i}.kr") for i in range(20)), NOW,
            RankConfig(minimum_score=0, max_items=10),
        )
        self.assertEqual((1, 5, 10), (len(quiet), len(normal), len(major)))

    def test_multi_publisher_pool_cannot_emit_single_publisher_digest(self):
        dominant = cluster("dominant", "one.kr", score="1")
        alternate = cluster("alternate", "two.kr", score=".9")
        selected = rank_clusters((dominant, alternate), NOW,
                                 RankConfig(minimum_score=0, max_items=1))
        self.assertEqual((), selected)

    def test_diversity_metrics_expose_quiet_day_shortage_and_ratios(self):
        one = cluster("one", "one.kr", region="domestic", investment=True)
        quiet = editorial_metrics((one,), approved_publishers=("one.kr",))
        self.assertTrue(quiet.insufficient_source_diversity)
        self.assertEqual((1.0, 1.0, 1.0),
                         (quiet.max_publisher_share, quiet.domestic_share, quiet.investment_share))
        diverse = editorial_metrics((one, cluster("two", "two.kr", region="overseas")),
                                    approved_publishers=("one.kr", "two.kr"))
        self.assertFalse(diverse.insufficient_source_diversity)
        self.assertEqual(2, diverse.publisher_count)


class GroundingTests(unittest.TestCase):
    def setUp(self):
        self.cluster = cluster("grounded", "evidence.kr")

    def test_fallback_uses_only_primary_evidence_and_citation(self):
        result = deterministic_fallback(self.cluster)
        self.assertEqual(result.sources[0].text, result.clauses[0].text)
        self.assertEqual(("E1",), result.clauses[0].evidence_ids)

    def test_malformed_or_unsupported_synthesis_falls_back(self):
        bad = json.dumps({"headline": "주장", "clauses": [
            {"text": "근거 없는 주장", "evidence_ids": ["E999"]},
        ]})
        result = summarize(self.cluster, bad)
        self.assertEqual(self.cluster.primary.title, result.headline)
        self.assertEqual(result.sources[0].text, result.clauses[0].text)

    def test_valid_synthesis_preserves_analysis_label_and_rejects_advice(self):
        valid = json.dumps({"headline": "요약", "clauses": [
            {"text": "정책 영향은 제한적일 수 있습니다.", "evidence_ids": ["E1"], "analysis": True},
        ]})
        self.assertTrue(parse_synthesis(self.cluster, valid).clauses[0].analysis)
        advice = json.dumps({"headline": "요약", "clauses": [
            {"text": "지금 매수하세요", "evidence_ids": ["E1"]},
        ]})
        with self.assertRaises(ValueError):
            parse_synthesis(self.cluster, advice)

    def test_valid_evidence_id_cannot_launder_an_invented_claim(self):
        invented = json.dumps({"headline": "요약", "clauses": [{
            "text": "화성에서 외계 생명체가 발견됐습니다.",
            "evidence_ids": ["E1"], "analysis": False,
        }]})
        with self.assertRaises(ValueError):
            parse_synthesis(self.cluster, invented)


class KakaoCompositionTests(unittest.TestCase):
    def assert_contract(self, composed):
        self.assertLessEqual(len(composed.messages), 18)
        self.assertTrue(all(len(message) <= 200 for message in composed.messages))
        self.assertLessEqual(composed.total_chars, 4000)
        total = len(composed.messages)
        self.assertTrue(all(message.startswith(f"[{i}/{total}] ")
                            for i, message in enumerate(composed.messages, 1)))
        self.assertIn(DISCLAIMER, composed.messages[-1])

    def test_quiet_normal_and_major_news_stay_within_contract(self):
        composer = DigestComposer()
        for count in (0, 5, 100):
            with self.subTest(count=count):
                digest = composer.compose(item(i) for i in range(count))
                self.assert_contract(digest)
                self.assertLessEqual(len(digest.messages), min(18, count + 2))

    def test_unicode_combining_emoji_and_newlines_use_final_string_count(self):
        fact = "정책\n변화 " + "가\u0301" * 20 + " 📈"
        digest = DigestComposer().compose((item(1, fact=fact),))
        self.assert_contract(digest)
        self.assertIn("📈", "".join(digest.messages))
        self.assertIn("\n", digest.messages[1])

    def test_oversized_story_and_long_link_are_dropped_not_split(self):
        long_url = "https://example.com/" + "x" * 220
        digest = DigestComposer().compose((item(1, url=long_url), item(2)))
        self.assert_contract(digest)
        joined = "\n".join(digest.messages)
        self.assertNotIn(long_url, joined)
        self.assertIn("https://source-2.kr/a/2", joined)

    def test_property_like_limits_across_item_and_text_sizes(self):
        composer = DigestComposer()
        for count in range(0, 31):
            for width in (0, 1, 20, 80, 140, 220):
                with self.subTest(count=count, width=width):
                    digest = composer.compose(
                        item(i, fact=("한" * width or f"사실 {i}")) for i in range(count)
                    )
                    self.assert_contract(digest)

    def test_custom_tight_total_limit_drops_items_before_mandatory_text(self):
        composer = DigestComposer(max_total=80)
        digest = composer.compose(tuple(item(i) for i in range(10)))
        self.assert_contract(digest)
        self.assertLessEqual(digest.total_chars, 80)

    def test_multiple_corroborating_citations_are_displayed(self):
        sources = (
            Evidence("E1", "정책 변화", "a.kr", "https://a.kr/x"),
            Evidence("E2", "정책 변화", "b.kr", "https://b.kr/y"),
        )
        digest_item = DigestItem(
            "multi", "정책 변화", (GroundedClause("정책 변화", ("E1", "E2")),), sources,
        )
        digest = DigestComposer().compose((digest_item,))
        self.assertIn("a.kr · https://a.kr/x", digest.messages[1])
        self.assertIn("b.kr · https://b.kr/y", digest.messages[1])
        self.assertFalse(digest.insufficient_source_diversity)

    def test_quiet_day_single_source_is_explicit(self):
        digest = DigestComposer().compose((item(1),))
        self.assertTrue(digest.insufficient_source_diversity)
        self.assertIn("독립 출처가 부족", digest.messages[0])


if __name__ == "__main__":
    unittest.main()
