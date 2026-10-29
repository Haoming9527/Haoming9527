#!/usr/bin/env python3
"""Fetch an auditable, complete public commit tape and derive weekly code candles.

Only Python's standard library is required. A failed API request leaves the last
successful output untouched. GITHUB_TOKEN is optional, but strongly recommended
because GitHub's unauthenticated API allowance is small.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time as clock
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


UTC = timezone.utc
API_ROOT = "https://api.github.com"
METHODOLOGY = (
    "One candle per UTC calendar week, starting Monday. The index starts at zero "
    "at the beginning of the displayed window. Commits are ordered by Git "
    "committer timestamp, then SHA. For each commit, additions raise the index "
    "before deletions lower it. Open is the previous close; high and low capture "
    "those constructed excursions; close is cumulative additions minus deletions. "
    "The additions-first convention is a visualization rule, not a measured "
    "within-commit timeline. Only commits authored by the configured GitHub user "
    "and reachable from selected public repositories' default branches are counted. "
    "Merge commits are excluded to avoid recounting merged changes. Identical "
    "SHAs across repositories are counted once. Binary-file changes may have zero "
    "line statistics. Line volume is activity, not productivity or financial value."
)


class CollectionError(RuntimeError):
    """A complete, trustworthy activity snapshot could not be collected."""


def iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_datetime(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return result.astimezone(UTC)


class GitHubClient:
    def __init__(self, token: str | None = None):
        self.token = token
        self.requests = 0

    def get(self, path_or_url: str) -> tuple[Any, dict[str, str]]:
        url = path_or_url if path_or_url.startswith("https://") else API_ROOT + path_or_url
        # Never forward an authorization token to a foreign pagination host.
        if urlsplit(url).scheme != "https" or urlsplit(url).netloc != "api.github.com":
            raise CollectionError("Refusing a pagination URL outside api.github.com")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Economist-profile-activity",
        }
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        for attempt in range(3):
            try:
                self.requests += 1
                with urlopen(Request(url, headers=headers), timeout=30) as response:
                    body = json.load(response)
                    return body, {key.lower(): value for key, value in response.headers.items()}
            except HTTPError as error:
                if error.code in (429, 500, 502, 503, 504) and attempt < 2:
                    clock.sleep(min(30, 2 ** (attempt + 1)))
                    continue
                detail = (
                    " GitHub API rate limit or permissions may be responsible; "
                    "use GITHUB_TOKEN with access to public repository contents."
                    if error.code in (401, 403, 429) else ""
                )
                raise CollectionError(f"GitHub API returned HTTP {error.code} for {url}.{detail}") from error
            except (URLError, TimeoutError) as error:
                if attempt < 2:
                    clock.sleep(2 ** (attempt + 1))
                    continue
                raise CollectionError(f"Could not reach GitHub API at {url}: {error}") from error
            except (ValueError, UnicodeError) as error:
                raise CollectionError(f"GitHub returned invalid JSON for {url}") from error
        raise AssertionError("Unreachable retry state")

    def pages(self, path: str):
        seen_urls: set[str] = set()
        next_url: str | None = path
        while next_url:
            if next_url in seen_urls:
                raise CollectionError("GitHub pagination repeated a URL")
            seen_urls.add(next_url)
            values, headers = self.get(next_url)
            if not isinstance(values, list):
                raise CollectionError("Expected a list in a GitHub paginated response")
            yield from values
            next_url = None
            for link in headers.get("link", "").split(","):
                match = re.search(r'<([^>]+)>;\s*rel="next"', link)
                if match:
                    next_url = match.group(1)
                    break


class ReplayClient(GitHubClient):
    """Replay previously fetched API responses without network or credentials.

    The file maps API paths (including query strings) or full URLs to objects
    with ``body`` and optional ``headers`` keys. Missing responses are errors,
    never empty results. Supply Link response headers for paginated collections.
    """

    def __init__(self, responses: dict[str, Any]):
        super().__init__()
        self.responses = responses

    def get(self, path_or_url: str) -> tuple[Any, dict[str, str]]:
        path = path_or_url.removeprefix(API_ROOT)
        entry = self.responses.get(path, self.responses.get(API_ROOT + path))
        if not isinstance(entry, dict) or "body" not in entry:
            raise CollectionError(f"Replay is missing an API response: {path}")
        self.requests += 1
        return entry["body"], {key.lower(): value for key, value in entry.get("headers", {}).items()}


def collect_open_source(username: str, client: GitHubClient) -> dict[str, Any]:
    """Count merged pull requests to repositories owned by other users/orgs."""
    query = f"is:pr author:{username} is:merged -user:{username} is:public"
    repositories: dict[str, int] = {}
    recent: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    expected: int | None = None
    page = 1
    while True:
        params = urlencode({"q": query, "sort": "updated", "order": "desc", "per_page": 100, "page": page})
        result, _ = client.get("/search/issues?" + params)
        if result.get("incomplete_results") is not False:
            raise CollectionError("GitHub open-source PR search returned incomplete results")
        total = result.get("total_count")
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise CollectionError("GitHub open-source PR search returned no valid total")
        if expected is None:
            expected = total
        elif expected != total:
            raise CollectionError("Open-source PR search changed while paging; retry the refresh")
        if total > 1000:
            raise CollectionError("Open-source PR search exceeds GitHub's 1,000-result limit; partition the query before refreshing")
        items = result.get("items")
        if not isinstance(items, list):
            raise CollectionError("GitHub open-source PR search returned no item list")
        for item in items:
            api_url = item.get("repository_url", "")
            if not api_url.startswith(API_ROOT + "/repos/"):
                raise CollectionError("PR search returned an unexpected repository URL")
            repository = api_url.removeprefix(API_ROOT + "/repos/")
            url = item.get("html_url", "")
            if not url.startswith(f"https://github.com/{repository}/pull/"):
                raise CollectionError("PR search returned an unexpected pull request URL")
            if repository.split("/")[0].lower() == username.lower():
                raise CollectionError("Open-source search unexpectedly included a self-owned repository")
            if url in seen_urls:
                raise CollectionError("Open-source search duplicated a pull request; retry the refresh")
            seen_urls.add(url)
            repositories[repository] = repositories.get(repository, 0) + 1
            if len(recent) < 5:
                recent.append({"title": item["title"], "url": url, "repository": repository,
                               "number": item["number"], "updated_at": item.get("updated_at")})
        if len(seen_urls) == expected:
            break
        if not items or len(seen_urls) > expected:
            raise CollectionError("Open-source PR search pagination did not match its reported total")
        page += 1
    return {
        "total_merged_prs": expected,
        "repository_count": len(repositories),
        "repositories": [{"name": name, "merged_prs": count, "url": f"https://github.com/{name}"}
                         for name, count in sorted(repositories.items(), key=lambda pair: (-pair[1], pair[0]))],
        "recent": recent,
        "recent_order": "Most recently updated merged pull requests",
        "query": query,
        "url": "https://github.com/search?" + urlencode({"q": query, "type": "issues"}),
        "scope": "Public merged pull requests authored by the user in repositories they do not own; all time",
    }


def validate_config(config: dict[str, Any]) -> tuple[str, list[str], int]:
    username = config.get("github_username", "")
    repositories = config.get("activity_repositories")
    days = config.get("activity_days", 90)
    if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", username):
        raise CollectionError("profile.json needs a valid github_username")
    if not isinstance(repositories, list) or not repositories:
        raise CollectionError("profile.json needs a nonempty activity_repositories list")
    if isinstance(days, bool) or not isinstance(days, int) or not 7 <= days <= 366:
        raise CollectionError("activity_days must be an integer between 7 and 366")
    normalized: list[str] = []
    seen: set[str] = set()
    for repository in repositories:
        if not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", repository):
            raise CollectionError(f"Invalid activity repository: {repository!r}")
        owner, name = repository.split("/")
        if owner.lower() != username.lower():
            raise CollectionError(f"Activity repository is not owned by {username}: {repository}")
        if name.lower() == username.lower():
            raise CollectionError("Exclude the profile repository to avoid counting automated refreshes")
        if repository.lower() not in seen:
            normalized.append(repository)
            seen.add(repository.lower())
    return username, normalized, days


def build_weeks(commits: list[dict[str, Any]], start: datetime, end: datetime) -> list[dict[str, Any]]:
    monday = start.date() - timedelta(days=start.weekday())
    weeks: dict[date, dict[str, Any]] = {}
    while monday <= end.date():
        sunday = monday + timedelta(days=6)
        weeks[monday] = {
            "start": monday.isoformat(),
            "end": sunday.isoformat(),
            "partial": monday < start.date() or sunday >= end.date(),
            "open": 0, "high": 0, "low": 0, "close": 0,
            "additions": 0, "deletions": 0, "commits": 0,
        }
        monday += timedelta(days=7)
    grouped: dict[date, list[dict[str, Any]]] = {key: [] for key in weeks}
    for commit in sorted(commits, key=lambda row: (parse_datetime(row["timestamp"]), row["sha"])):
        timestamp = parse_datetime(commit["timestamp"])
        if start <= timestamp <= end:
            grouped[timestamp.date() - timedelta(days=timestamp.weekday())].append(commit)
    index = 0
    for monday, week in weeks.items():
        week.update(open=index, high=index, low=index, close=index)
        for commit in grouped[monday]:
            additions, deletions = commit["additions"], commit["deletions"]
            index += additions
            week["high"] = max(week["high"], index)
            index -= deletions
            week["low"] = min(week["low"], index)
            week["close"] = index
            week["additions"] += additions
            week["deletions"] += deletions
            week["commits"] += 1
    return list(weeks.values())


def collect(config: dict[str, Any], client: GitHubClient, now: datetime,
            progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    username, repositories, days = validate_config(config)
    end = now.astimezone(UTC).replace(microsecond=0)
    start = datetime.combine(end.date() - timedelta(days=days - 1), time.min, UTC)
    commits: list[dict[str, Any]] = []
    repository_totals: list[dict[str, Any]] = []
    seen_shas: set[str] = set()
    exclusions = {"merge_commits": 0, "duplicate_commits": 0, "other_authors": 0, "outside_window": 0}
    for repository in repositories:
        if progress:
            progress(f"Reading {repository}...")
        metadata, _ = client.get(f"/repos/{repository}")
        if metadata.get("private") is not False or metadata.get("visibility", "public") != "public":
            raise CollectionError(f"Refusing to publish activity from a nonpublic repository: {repository}")
        if metadata.get("owner", {}).get("login", "").lower() != username.lower():
            raise CollectionError(f"Repository ownership no longer matches {username}: {repository}")
        default_branch = metadata.get("default_branch")
        if not isinstance(default_branch, str) or not default_branch:
            raise CollectionError(f"No default branch found for {repository}")
        repo_summary = {"name": repository, "default_branch": default_branch,
                        "commits": 0, "additions": 0, "deletions": 0}
        # GitHub reports size zero for empty repositories. Querying their commit
        # endpoint produces 409; branch existence distinguishes them from errors.
        if metadata.get("size") == 0:
            branches = list(client.pages(f"/repos/{repository}/branches?per_page=100"))
            if not branches:
                repository_totals.append(repo_summary)
                continue
        query = urlencode({"sha": default_branch, "author": username,
                           "since": iso(start), "until": iso(end), "per_page": 100})
        for summary in client.pages(f"/repos/{repository}/commits?{query}"):
            sha = summary.get("sha", "")
            if not re.fullmatch(r"[0-9a-f]{40,64}", sha):
                raise CollectionError(f"Invalid commit SHA returned for {repository}")
            author = summary.get("author") or {}
            if author.get("login", "").lower() != username.lower():
                exclusions["other_authors"] += 1
                continue
            if len(summary.get("parents", [])) > 1:
                exclusions["merge_commits"] += 1
                continue
            timestamp = summary.get("commit", {}).get("committer", {}).get("date")
            try:
                committed_at = parse_datetime(timestamp)
            except (TypeError, AttributeError, ValueError) as error:
                raise CollectionError(f"Missing commit timestamp for {repository}/{sha}") from error
            if not start <= committed_at <= end:
                exclusions["outside_window"] += 1
                continue
            if sha in seen_shas:
                exclusions["duplicate_commits"] += 1
                continue
            detail, _ = client.get(f"/repos/{repository}/commits/{sha}")
            stats = detail.get("stats") or {}
            additions, deletions = stats.get("additions"), stats.get("deletions")
            if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
                   for value in (additions, deletions)):
                raise CollectionError(f"Missing line statistics for {repository}/{sha}")
            seen_shas.add(sha)
            commits.append({"sha": sha, "repository": repository, "timestamp": iso(committed_at),
                            "additions": additions, "deletions": deletions,
                            "url": f"https://github.com/{repository}/commit/{sha}"})
            repo_summary["commits"] += 1
            repo_summary["additions"] += additions
            repo_summary["deletions"] += deletions
        repository_totals.append(repo_summary)
        if progress:
            progress(f"  {repo_summary['commits']} authored commits; "
                     f"+{repo_summary['additions']} / -{repo_summary['deletions']} lines")
    commits.sort(key=lambda row: (row["timestamp"], row["sha"]))
    weeks = build_weeks(commits, start, end)
    additions = sum(row["additions"] for row in commits)
    deletions = sum(row["deletions"] for row in commits)
    if progress:
        progress("Reading public merged pull requests to other repositories...")
    open_source = collect_open_source(username, client)
    return {
        "schema_version": 1,
        "github_username": username,
        "generated_at": iso(end),
        "window": {"start": iso(start), "end": iso(end), "days": days, "timezone": "UTC"},
        "totals": {"additions": additions, "deletions": deletions, "commits": len(commits),
                   "net_lines": additions - deletions, "active_weeks": sum(week["commits"] > 0 for week in weeks)},
        "weeks": weeks,
        "repositories": repository_totals,
        "coverage": {"scope": "Selected public owned repositories; default branches; authored non-merge commits",
                     "complete": True, "repository_count": len(repositories),
                     "api_requests": client.requests, "excluded": exclusions},
        "warnings": [],
        "methodology": METHODOLOGY,
        "commits": commits,
        "open_source": open_source,
    }


def write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(snapshot, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("profile.json"))
    parser.add_argument("--output", type=Path, default=Path("data/activity.json"))
    parser.add_argument("--now", help="Explicit ISO timestamp for reproducible snapshots (default: current UTC)")
    parser.add_argument("--responses", type=Path, help="Replay a JSON map of previously fetched API responses")
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8-sig"))
        now = parse_datetime(args.now) if args.now else datetime.now(UTC)
        client = (ReplayClient(json.loads(args.responses.read_text(encoding="utf-8-sig"))) if args.responses
                  else GitHubClient(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")))
        snapshot = collect(config, client, now, lambda message: print(message, file=sys.stderr, flush=True))
        write_snapshot(args.output, snapshot)
    except (CollectionError, OSError, ValueError) as error:
        print(f"Activity refresh failed; previous snapshot preserved: {error}", file=sys.stderr)
        return 1
    print(f"Wrote {args.output}: {snapshot['totals']['commits']} commits across "
          f"{snapshot['coverage']['repository_count']} public repositories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
