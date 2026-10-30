"""Builds the snapshot: configuration checks, cached all-time commits and the weekly candles."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable
from urllib.parse import urlencode

import catalog

from .github import CollectionError, GitHubClient, UTC, iso, parse_datetime
from .sources import collect_open_source, collect_stars, commit_detail, detect_stack, resolve_logos


METHODOLOGY = (
    "Candles cover UTC days, Monday-start weeks, months, quarters or years. The "
    "index starts at zero before the first collected commit. Commits are ordered by Git "
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


def contribution_exclusions(config: dict[str, Any]) -> list[str]:
    exclusions = config.get("contribution_exclusions", [])
    if not isinstance(exclusions, list) or not all(
            isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", name) for name in exclusions):
        raise CollectionError("contribution_exclusions must be a list of owner/repository names")
    return exclusions


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
            progress: Callable[[str], None] | None = None, previous: dict[str, Any] | None = None,
            fetch: Callable[[str], str | None] | None = None) -> dict[str, Any]:
    username, repositories, days = validate_config(config)
    exclusion_names = contribution_exclusions(config)
    previous = previous if (previous or {}).get("schema_version") == 3 else {}
    cached_repos = {row["name"].lower(): row for row in previous.get("repositories", [])}
    cached_commits = {row["sha"]: row for row in previous.get("commits", [])}
    end = now.astimezone(UTC).replace(microsecond=0)
    start = datetime.combine(end.date() - timedelta(days=days - 1), time.min, UTC)
    commits: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    seen_shas: set[str] = set()
    exclusions = {"merge_commits": 0, "duplicate_commits": 0, "other_authors": 0}
    reused = 0
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
        row = {"name": repository, "default_branch": default_branch, "pushed_at": metadata.get("pushed_at"),
               "stars": metadata.get("stargazers_count", 0), "language": metadata.get("language"),
               "rules": catalog.RULES_VERSION, "shas": [], "languages": {}, "stack": [],
               "excluded": dict.fromkeys(("merge_commits", "other_authors"), 0)}
        cached = cached_repos.get(repository.lower())
        if (cached and cached.get("pushed_at") == row["pushed_at"] and cached.get("default_branch") == default_branch
                and all(sha in cached_commits for sha in cached["shas"])):
            # Nothing was pushed since the last snapshot, so nothing can have changed.
            row.update(shas=cached["shas"], languages=cached["languages"], excluded=cached["excluded"],
                       stack=cached["stack"] if cached.get("rules") == catalog.RULES_VERSION
                       else detect_stack(repository, default_branch, client))
            reused += 1
        elif metadata.get("size") == 0 and not list(client.pages(f"/repos/{repository}/branches?per_page=100")):
            pass  # Empty repository: GitHub answers 409 for its commits.
        else:
            query = urlencode({"sha": default_branch, "author": username, "until": iso(end), "per_page": 100})
            for summary in client.pages(f"/repos/{repository}/commits?{query}"):
                sha = summary.get("sha", "")
                if not re.fullmatch(r"[0-9a-f]{40,64}", sha):
                    raise CollectionError(f"Invalid commit SHA returned for {repository}")
                if (summary.get("author") or {}).get("login", "").lower() != username.lower():
                    row["excluded"]["other_authors"] += 1
                    continue
                if len(summary.get("parents", [])) > 1:
                    row["excluded"]["merge_commits"] += 1
                    continue
                try:
                    committed_at = parse_datetime(summary.get("commit", {}).get("committer", {}).get("date"))
                except (TypeError, AttributeError, ValueError) as error:
                    raise CollectionError(f"Missing commit timestamp for {repository}/{sha}") from error
                if sha not in cached_commits:
                    cached_commits[sha] = commit_detail(repository, sha, committed_at, client)
                row["shas"].append(sha)
            languages, _ = client.get(f"/repos/{repository}/languages")
            if not isinstance(languages, dict) or any(
                    isinstance(size, bool) or not isinstance(size, int) or size < 0 for size in languages.values()):
                raise CollectionError(f"Invalid language breakdown for {repository}")
            row["languages"] = languages
            row["stack"] = detect_stack(repository, default_branch, client)
        for key, count in row["excluded"].items():
            exclusions[key] += count
        for sha in row["shas"]:
            if sha in seen_shas:
                exclusions["duplicate_commits"] += 1
                continue
            seen_shas.add(sha)
            commits.append(cached_commits[sha])
        rows.append(row)
        if progress:
            progress(f"  {len(row['shas'])} authored commits" + (" (unchanged)" if cached and row["shas"] is cached["shas"] else ""))
    commits.sort(key=lambda commit: (commit["timestamp"], commit["sha"]))
    window = [commit for commit in commits if start <= parse_datetime(commit["timestamp"]) <= end]
    weeks = build_weeks(window, start, end)
    additions = sum(commit["additions"] for commit in window)
    deletions = sum(commit["deletions"] for commit in window)
    if progress:
        progress("Reading public merged pull requests and stargazers...")
    open_source = collect_open_source(username, client, exclusion_names)
    targets = [(row["name"], row["stars"]) for row in rows]
    for external in open_source["repositories"]:
        metadata, _ = client.get(f"/repos/{external['name']}")
        external["stars"] = metadata.get("stargazers_count", 0)
        external["language"] = metadata.get("language")
        targets.append((external["name"], external["stars"]))
    stars = collect_stars(targets, client, previous.get("stars"), end.date().isoformat())
    language_bytes: dict[str, int] = {}
    stack: dict[str, list[str]] = {}
    for row in rows:
        for language, size in row["languages"].items():
            language_bytes[language] = language_bytes.get(language, 0) + size
        for tool in row["stack"]:
            stack.setdefault(tool, []).append(row["name"])
    logos = resolve_logos(list(language_bytes) + list(stack), previous.get("logos", {}), end.date().isoformat(), fetch)
    return {
        "schema_version": 3,
        "github_username": username,
        "generated_at": iso(end),
        "window": {"start": iso(start), "end": iso(end), "days": days, "timezone": "UTC"},
        "totals": {"additions": additions, "deletions": deletions, "commits": len(window),
                   "net_lines": additions - deletions, "active_weeks": sum(week["commits"] > 0 for week in weeks)},
        "weeks": weeks,
        "repositories": rows,
        "coverage": {"scope": "Selected public owned repositories; default branches; authored non-merge commits; all time",
                     "complete": True, "repository_count": len(repositories), "reused_repositories": reused,
                     "api_requests": client.requests, "excluded": exclusions,
                     "commits_with_truncated_file_lists": sum(commit.get("files_truncated", False) for commit in commits)},
        "warnings": [],
        "methodology": METHODOLOGY,
        "commits": commits,
        "open_source": open_source,
        "languages": {"bytes": dict(sorted(language_bytes.items(), key=lambda pair: (-pair[1], pair[0]))),
                      "scope": "GitHub Linguist bytes in the configured public repositories' default branches"},
        "stack": dict(sorted(stack.items())),
        "logos": logos,
        "stars": stars,
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


def load_previous(path: Path) -> dict[str, Any] | None:
    """The last snapshot seeds the cache; an unreadable one just means a full refresh."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
