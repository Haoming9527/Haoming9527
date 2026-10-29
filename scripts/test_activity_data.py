"""Checks for financial-style code candles and safe, complete API collection."""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import activity_data as activity


NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
CONFIG = {"github_username": "Haoming9527", "activity_repositories": ["Haoming9527/example"]}


def commit(sha="a" * 40, timestamp="2026-10-26T12:00:00Z", author="Haoming9527", parents=1):
    return {"sha": sha, "author": {"login": author} if author else None,
            "parents": [{}] * parents, "commit": {"committer": {"date": timestamp}}}


class FakeClient(activity.GitHubClient):
    def __init__(self, summaries=None, stats=None, private=False):
        super().__init__()
        self.summaries = summaries if summaries is not None else [commit()]
        self.stats = stats if stats is not None else {"additions": 20, "deletions": 7}
        self.private = private

    def get(self, path):
        self.requests += 1
        if path.startswith("/search/issues?"):
            return {"total_count": 0, "incomplete_results": False, "items": []}, {}
        if "/commits?" in path:
            return self.summaries, {}
        if "/commits/" in path:
            return {"stats": self.stats}, {}
        return {"private": self.private, "owner": {"login": "Haoming9527"},
                "default_branch": "main", "size": 1}, {}


class CandleTests(unittest.TestCase):
    def test_positive_negative_and_empty_weeks(self):
        start = activity.parse_datetime("2026-10-05T00:00:00Z")
        end = activity.parse_datetime("2026-10-25T23:59:59Z")
        tape = [
            {"sha": "b", "timestamp": "2026-10-12T00:00:00Z", "additions": 3, "deletions": 20},
            {"sha": "a", "timestamp": "2026-10-05T00:00:00Z", "additions": 10, "deletions": 2},
        ]
        bars = activity.build_weeks(tape, start, end)
        self.assertEqual([(bar["open"], bar["high"], bar["low"], bar["close"]) for bar in bars],
                         [(0, 10, 0, 8), (8, 11, -9, -9), (-9, -9, -9, -9)])
        self.assertEqual([bar["commits"] for bar in bars], [1, 1, 0])

    def test_multiple_commits_capture_intraweek_excursions(self):
        tape = [
            {"sha": "a", "timestamp": "2026-10-26T00:00:00Z", "additions": 5, "deletions": 12},
            {"sha": "b", "timestamp": "2026-10-27T00:00:00Z", "additions": 20, "deletions": 1},
        ]
        bar = activity.build_weeks(tape, activity.parse_datetime("2026-10-26T00:00:00Z"), NOW)[0]
        self.assertEqual((bar["open"], bar["high"], bar["low"], bar["close"]), (0, 13, -7, 12))
        self.assertTrue(bar["partial"])

    def test_timezone_and_window_boundary(self):
        start = activity.parse_datetime("2026-10-26T00:00:00Z")
        tape = [
            {"sha": "a", "timestamp": "2026-10-26T07:59:59+08:00", "additions": 100, "deletions": 0},
            {"sha": "b", "timestamp": "2026-10-26T08:00:00+08:00", "additions": 9, "deletions": 1},
        ]
        bar = activity.build_weeks(tape, start, NOW)[0]
        self.assertEqual(bar["commits"], 1)
        self.assertEqual(bar["close"], 8)

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            activity.parse_datetime("2026-10-26T00:00:00")


class CollectionTests(unittest.TestCase):
    def test_deduplicates_and_filters_merges_other_authors_and_old_commits(self):
        client = FakeClient([
            commit(), commit(), commit("b" * 40, author="dependabot[bot]"),
            commit("c" * 40, parents=2), commit("d" * 40, timestamp="2025-10-26T12:00:00Z"),
            commit("e" * 40, author=None),
        ])
        snapshot = activity.collect(CONFIG, client, NOW)
        self.assertEqual(snapshot["totals"]["commits"], 1)
        self.assertEqual(snapshot["totals"]["net_lines"], 13)
        self.assertEqual(snapshot["coverage"]["excluded"],
                         {"merge_commits": 1, "duplicate_commits": 1, "other_authors": 2, "outside_window": 1})
        self.assertEqual(snapshot["window"]["start"], "2026-08-02T00:00:00Z")

    def test_deduplicates_same_sha_across_repositories(self):
        config = dict(CONFIG, activity_repositories=["Haoming9527/example", "Haoming9527/other"])
        snapshot = activity.collect(config, FakeClient(), NOW)
        self.assertEqual(snapshot["totals"]["commits"], 1)
        self.assertEqual([repo["commits"] for repo in snapshot["repositories"]], [1, 0])

    def test_missing_stats_or_private_repository_fails(self):
        for client in (FakeClient(stats={}), FakeClient(private=True)):
            with self.subTest(client=client), self.assertRaises(activity.CollectionError):
                activity.collect(CONFIG, client, NOW)

    def test_profile_repository_and_foreign_owner_rejected(self):
        for repository in ("Haoming9527/Haoming9527", "someone/example"):
            with self.subTest(repository=repository), self.assertRaises(activity.CollectionError):
                activity.validate_config(dict(CONFIG, activity_repositories=[repository]))

    def test_pagination_follows_link_and_detects_loop(self):
        client = activity.ReplayClient({
            "/page1": {"body": [1], "headers": {"Link": '<https://api.github.com/page2>; rel="next"'}},
            "/page2": {"body": [2]},
        })
        self.assertEqual(list(client.pages("/page1")), [1, 2])
        client.responses["/page2"]["headers"] = {"Link": '<https://api.github.com/page2>; rel="next"'}
        with self.assertRaises(activity.CollectionError):
            list(client.pages("/page1"))

    def test_foreign_pagination_host_rejected_before_request(self):
        with self.assertRaises(activity.CollectionError):
            activity.GitHubClient("never-send-me").get("https://example.com/page2")

    def test_failed_refresh_preserves_existing_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path, output_path = Path(directory) / "profile.json", Path(directory) / "activity.json"
            config_path.write_text(json.dumps(CONFIG), encoding="utf-8")
            output_path.write_text("previous complete snapshot", encoding="utf-8")
            with patch.object(activity.GitHubClient, "get", side_effect=activity.CollectionError("request failed")):
                result = activity.main(["--config", str(config_path), "--output", str(output_path)])
            self.assertEqual(result, 1)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "previous complete snapshot")


class OpenSourceTests(unittest.TestCase):
    @staticmethod
    def item(number):
        return {"repository_url": "https://api.github.com/repos/other/project",
                "html_url": f"https://github.com/other/project/pull/{number}",
                "title": f"Change {number}", "number": number, "updated_at": "2026-10-30T00:00:00Z"}

    def test_pr_search_pagination_and_repository_counts(self):
        client = activity.GitHubClient()
        def get(path):
            query = parse_qs(urlsplit(path).query)
            self.assertIn("is:public", query["q"][0].split())
            page = int(query["page"][0])
            items = [self.item(i) for i in (range(1, 101) if page == 1 else [101])]
            return {"total_count": 101, "incomplete_results": False, "items": items}, {}
        client.get = get
        result = activity.collect_open_source("Haoming9527", client)
        self.assertEqual(result["total_merged_prs"], 101)
        self.assertEqual(result["repository_count"], 1)
        self.assertEqual(result["repositories"][0]["merged_prs"], 101)
        self.assertEqual(len(result["recent"]), 5)

    def test_incomplete_and_truncated_search_fail(self):
        for response in ({"incomplete_results": True},
                         {"incomplete_results": False, "total_count": 1001, "items": []},
                         {"incomplete_results": False, "total_count": 1, "items": []}):
            client = activity.GitHubClient()
            client.get = lambda path: (response, {})
            with self.subTest(response=response), self.assertRaises(activity.CollectionError):
                activity.collect_open_source("Haoming9527", client)


if __name__ == "__main__":
    unittest.main()
