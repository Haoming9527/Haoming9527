"""Checks for financial-style code candles and safe, complete, incremental API collection."""

import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import activity_data as activity


NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
CONFIG = {"github_username": "Haoming9527"}
PACKAGE = base64.b64encode(json.dumps({"dependencies": {"react": "19", "ai": "7"}}).encode()).decode()


def commit(sha="a" * 40, timestamp="2026-10-26T12:00:00Z", author="Haoming9527", parents=1):
    return {"sha": sha, "author": {"login": author} if author else None,
            "parents": [{}] * parents, "commit": {"committer": {"date": timestamp}}}


def owned(name, private=False, fork=False):
    return {"full_name": f"Haoming9527/{name}", "private": private, "fork": fork}


class FakeClient(activity.GitHubClient):
    def __init__(self, summaries=None, stats=None, private=False, files=None, stars=2, repos=None):
        super().__init__()
        self.summaries = summaries if summaries is not None else [commit()]
        self.stats = stats if stats is not None else {"additions": 20, "deletions": 7}
        self.private = private
        self.files = files or []
        self.stars = stars
        self.repos = repos if repos is not None else [owned("example")]
        self.paths = []

    def get(self, path, accept=None):
        self.requests += 1
        self.paths.append(path)
        if path.startswith("/users/Haoming9527/repos?"):
            return self.repos, {}
        if path.startswith("/search/issues?"):
            return {"total_count": 0, "incomplete_results": False, "items": []}, {}
        if "/commits?" in path:
            return self.summaries, {}
        if "/commits/" in path:
            return {"stats": self.stats, "files": self.files}, {}
        if path.endswith("/languages"):
            return {"TypeScript": 300, "CSS": 100}, {}
        if "/git/trees/" in path:
            return {"tree": [{"path": "package.json", "type": "blob"}, {"path": "api/Dockerfile", "type": "blob"},
                             {"path": "node_modules/x/package.json", "type": "blob"}]}, {}
        if "/contents/" in path:
            return {"content": PACKAGE}, {}
        if "/stargazers?" in path:
            self.star_accept = accept
            return [{"starred_at": f"2026-10-0{1 + i}T03:00:00Z"} for i in range(self.stars)], {}
        return {"private": self.private, "owner": {"login": "Haoming9527"}, "default_branch": "main",
                "size": 1, "pushed_at": "2026-10-29T00:00:00Z", "stargazers_count": self.stars}, {}


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
    def test_deduplicates_filters_and_keeps_history_outside_the_window(self):
        client = FakeClient([
            commit(), commit(), commit("b" * 40, author="dependabot[bot]"),
            commit("c" * 40, parents=2), commit("d" * 40, timestamp="2025-10-26T12:00:00Z"),
            commit("e" * 40, author=None),
        ])
        snapshot = activity.collect(CONFIG, client, NOW)
        self.assertEqual(snapshot["totals"]["commits"], 1)
        self.assertEqual(snapshot["totals"]["net_lines"], 13)
        self.assertEqual([row["sha"][0] for row in snapshot["commits"]], ["d", "a"])
        self.assertEqual(snapshot["coverage"]["excluded"],
                         {"merge_commits": 1, "duplicate_commits": 1, "other_authors": 2})
        self.assertEqual(snapshot["window"]["start"], "2026-08-02T00:00:00Z")
        listing = next(path for path in client.paths if "/commits?" in path)
        self.assertNotIn("since=", listing)

    def test_deduplicates_same_sha_across_repositories(self):
        client = FakeClient(repos=[owned("example"), owned("other")])
        snapshot = activity.collect(CONFIG, client, NOW)
        self.assertEqual(len(snapshot["commits"]), 1)
        self.assertEqual(snapshot["coverage"]["excluded"]["duplicate_commits"], 1)
        self.assertEqual(sum("/commits/" in path for path in client.paths), 1)

    def test_missing_stats_or_private_repository_fails(self):
        for client in (FakeClient(stats={}), FakeClient(private=True)):
            with self.subTest(client=client), self.assertRaises(activity.CollectionError):
                activity.collect(CONFIG, client, NOW)

    def test_every_public_repository_counts_except_forks_profile_and_exclusions(self):
        repos = [owned("Zeta"), owned("alpha"), owned("forked", fork=True), owned("Haoming9527"),
                 owned("secret", private=True), owned("skip")]
        config = dict(CONFIG, activity_exclusions=["Haoming9527/skip"])
        snapshot = activity.collect(config, FakeClient(repos=repos), NOW)
        self.assertEqual([row["name"] for row in snapshot["repositories"]], ["Haoming9527/alpha", "Haoming9527/Zeta"])
        self.assertEqual(snapshot["coverage"]["repository_count"], 2)
        self.assertEqual(snapshot["coverage"]["excluded_repositories"], ["Haoming9527/skip"])

    def test_a_new_repository_is_counted_on_the_next_refresh(self):
        first = activity.collect(CONFIG, FakeClient(), NOW)
        second = activity.collect(CONFIG, FakeClient(repos=[owned("example"), owned("brand-new")]), NOW, previous=first)
        self.assertEqual([row["name"] for row in second["repositories"]], ["Haoming9527/brand-new", "Haoming9527/example"])
        self.assertEqual(second["coverage"]["reused_repositories"], 1)

    def test_foreign_or_invalid_names_are_rejected(self):
        for exclusions in (["someone/example"], ["not a repository"], "Haoming9527/example"):
            with self.subTest(exclusions=exclusions), self.assertRaises(activity.CollectionError):
                activity.validate_config(dict(CONFIG, activity_exclusions=exclusions))
        with self.assertRaises(activity.CollectionError):
            activity.collect(CONFIG, FakeClient(repos=[{"full_name": "someone/example", "private": False, "fork": False}]), NOW)
        with self.assertRaises(activity.CollectionError):
            activity.collect(CONFIG, FakeClient(repos=[owned("forked", fork=True)]), NOW)

    def test_language_lines_stack_stars_and_bytes(self):
        files = [{"filename": "src/app.tsx", "additions": 12, "deletions": 3},
                 {"filename": "styles/site.css", "additions": 4, "deletions": 4},
                 {"filename": "package-lock.json", "additions": 900, "deletions": 0},
                 {"filename": "node_modules/x/index.js", "additions": 50, "deletions": 0},
                 {"filename": "docker/Dockerfile", "additions": 2, "deletions": 0}]
        client = FakeClient(files=files)
        snapshot = activity.collect(CONFIG, client, NOW)
        self.assertEqual(snapshot["commits"][0]["languages"],
                         {"TypeScript": [12, 3], "CSS": [4, 4], "Dockerfile": [2, 0]})
        self.assertEqual(snapshot["languages"]["bytes"], {"TypeScript": 300, "CSS": 100})
        self.assertEqual(snapshot["stack"], {tool: ["Haoming9527/example"]
                                             for tool in ("AI SDK", "Docker", "Node.js", "React")})
        self.assertEqual(snapshot["stars"]["total"], 2)
        self.assertEqual(snapshot["stars"]["repositories"][0]["starred_on"], {"2026-10-01": 1, "2026-10-02": 1})
        self.assertEqual(client.star_accept, activity.STAR_ACCEPT)

    def test_unchanged_repository_reuses_previous_snapshot(self):
        first = activity.collect(CONFIG, FakeClient(), NOW)
        client = FakeClient()
        second = activity.collect(CONFIG, client, NOW, previous=first)
        self.assertEqual(second["coverage"]["reused_repositories"], 1)
        self.assertEqual(second["commits"], first["commits"])
        self.assertFalse([path for path in client.paths
                          if any(part in path for part in ("/commits", "/languages", "/git/trees", "/stargazers"))])

    def test_new_stars_only_read_the_newest_page(self):
        first = activity.collect(CONFIG, FakeClient(stars=2), NOW)
        client = FakeClient(stars=3)
        second = activity.collect(CONFIG, client, NOW, previous=first)
        star_requests = [path for path in client.paths if "/stargazers?" in path]
        self.assertEqual(len(star_requests), 1)
        self.assertIn("page=1", star_requests[0])
        self.assertEqual(second["stars"]["repositories"][0]["starred_on"],
                         {"2026-10-01": 1, "2026-10-02": 1, "2026-10-03": 1})

    def test_stack_detection_reads_every_ecosystem(self):
        files = {
            "web/package.json": json.dumps({"dependencies": {"next": "16", "@ai-sdk/openai": "4"},
                                            "devDependencies": {"tailwindcss": "4"}}),
            "api/requirements.txt": "FastAPI==0.115\n# comment\ntorch>=2\n",
            "svc/pyproject.toml": '[project]\ndependencies = ["langchain>=0.3", "psycopg[binary]"]\n',
            "go/go.mod": "module x\nrequire github.com/gin-gonic/gin v1.10.0\n",
            "deploy/compose.yml": "services:\n  llm:\n    image: ollama/ollama\n",
        }
        client = activity.GitHubClient()
        def get(path, accept=None):
            if "/git/trees/" in path:
                return {"tree": [{"path": name, "type": "blob"} for name in [*files, "infra/main.tf", "node_modules/a/package.json"]]}, {}
            name = next(name for name in files if path.split("/contents/")[1].startswith(name.replace("/", "%2F"))
                        or path.split("/contents/")[1].startswith(name))
            return {"content": base64.b64encode(files[name].encode()).decode()}, {}
        client.get = get
        self.assertEqual(activity.detect_stack("Haoming9527/example", "main", client),
                         ["AI SDK", "Docker", "FastAPI", "Gin", "LangChain", "Next.js", "Node.js", "Ollama", "OpenAI",
                          "PostgreSQL", "PyTorch", "Tailwind CSS", "Terraform"])

    def test_logos_resolve_once_and_cache_misses_for_a_day(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return '<svg viewBox="0 0 24 24"><script>x</script><path d="M0 0"/></svg>' if "python" in url else None
        logos = activity.resolve_logos(["Python", "JavaScript", "Mystery Lang"], {}, "2026-10-30", fetch)
        self.assertNotIn("JavaScript", logos)
        self.assertIn("<path", logos["Python"]["svg"])
        self.assertNotIn("script", logos["Python"]["svg"])
        self.assertEqual(logos["Mystery Lang"], {"missing": True, "checked": "2026-10-30"})
        calls.clear()
        again = activity.resolve_logos(["Python", "Mystery Lang"], logos, "2026-10-30", fetch)
        self.assertEqual((again, calls), (logos, []))

    def test_hidden_stargazer_list_keeps_the_count_without_dates(self):
        client = activity.GitHubClient()
        def get(path, accept=None):
            raise activity.NotFound("HTTP 404")
        client.get = get
        stars = activity.collect_stars([("other/project", 7)], client)
        self.assertEqual(stars["total"], 7)
        self.assertEqual(stars["repositories"][0], {"name": "other/project", "stars": 7, "starred_on": {}, "undated": 7})

    def test_refused_stargazer_list_dates_new_stars_when_first_seen(self):
        client = activity.GitHubClient()
        def get(path, accept=None):
            raise activity.Unavailable("HTTP 403")
        client.get = get
        previous = {"repositories": [{"name": "other/project", "stars": 5, "starred_on": {"2026-10-01": 5}}]}
        stars = activity.collect_stars([("other/project", 8)], client, previous, "2026-10-30")
        self.assertEqual(stars["repositories"][0],
                         {"name": "other/project", "stars": 8, "starred_on": {"2026-10-01": 5, "2026-10-30": 3}})
        self.assertEqual(stars["dated_on_observation"], ["other/project"])
        fewer = activity.collect_stars([("other/project", 4)], client, previous, "2026-10-30")
        self.assertEqual(fewer["repositories"][0]["undated"], -1)
        self.assertEqual(fewer["total"], 4)

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
            output_path.write_text('{"schema_version": 3}', encoding="utf-8")
            with patch.object(activity.GitHubClient, "get", side_effect=activity.CollectionError("request failed")):
                result = activity.main(["--config", str(config_path), "--output", str(output_path)])
            self.assertEqual(result, 1)
            self.assertEqual(output_path.read_text(encoding="utf-8"), '{"schema_version": 3}')


class OpenSourceTests(unittest.TestCase):
    @staticmethod
    def item(number, repository="other/project"):
        return {"repository_url": f"https://api.github.com/repos/{repository}",
                "html_url": f"https://github.com/{repository}/pull/{number}",
                "title": f"Change {number}", "number": number, "updated_at": "2026-10-30T00:00:00Z",
                "pull_request": {"merged_at": f"2026-10-{1 + number % 28:02d}T00:00:00Z"}}

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

    def test_exclusions_join_query_and_merge_dates_are_kept(self):
        client = activity.GitHubClient()
        queries = []
        def get(path):
            queries.append(parse_qs(urlsplit(path).query)["q"][0].split())
            return {"total_count": 2, "incomplete_results": False, "items": [self.item(2), self.item(1)]}, {}
        client.get = get
        result = activity.collect_open_source("Haoming9527", client, ["gone/project"])
        self.assertIn("-repo:gone/project", queries[0])
        self.assertEqual(result["repositories"][0]["merged_at"], ["2026-10-02T00:00:00Z", "2026-10-03T00:00:00Z"])

    def test_own_repository_prs_count_in_the_total_but_not_as_collaborations(self):
        client = activity.GitHubClient()
        queries = []
        def get(path):
            queries.append(parse_qs(urlsplit(path).query)["q"][0].split())
            items = [self.item(1), self.item(2, "Haoming9527/app"), self.item(3, "haoming9527/tool")]
            return {"total_count": 3, "incomplete_results": False, "items": items}, {}
        client.get = get
        result = activity.collect_open_source("Haoming9527", client)
        self.assertNotIn("-user:Haoming9527", queries[0])
        self.assertEqual(result["total_merged_prs"], 3)
        self.assertEqual(result["external_merged_prs"], 1)
        self.assertEqual([row["name"] for row in result["repositories"]], ["other/project"])
        self.assertEqual([row["name"] for row in result["owned_repositories"]], ["Haoming9527/app", "haoming9527/tool"])
        self.assertIn("-user%3AHaoming9527", result["external_url"])

    def test_incomplete_truncated_or_undated_search_fails(self):
        missing = dict(self.item(1), pull_request={})
        for response in ({"incomplete_results": True},
                         {"incomplete_results": False, "total_count": 1001, "items": []},
                         {"incomplete_results": False, "total_count": 1, "items": []},
                         {"incomplete_results": False, "total_count": 1, "items": [missing]}):
            client = activity.GitHubClient()
            client.get = lambda path, response=response: (response, {})
            with self.subTest(response=response), self.assertRaises(activity.CollectionError):
                activity.collect_open_source("Haoming9527", client)


if __name__ == "__main__":
    unittest.main()
