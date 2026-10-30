#!/usr/bin/env python3
"""Fetch an auditable, complete public commit tape for the market board.

Only Python's standard library is required. A failed API request leaves the last
successful output untouched. GITHUB_TOKEN is optional, but strongly recommended
because GitHub's unauthenticated API allowance is small.

Refreshes are incremental so they can run every few minutes: repositories whose
pushed_at did not move reuse the previous snapshot, commit statistics are cached
by SHA (they never change), and stargazer histories only fetch their newest pages.
"""

from __future__ import annotations

import argparse
import base64
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import time as clock
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

import catalog


UTC = timezone.utc
API_ROOT = "https://api.github.com"
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
STAR_ACCEPT = "application/vnd.github.star+json"
# Names follow GitHub Linguist so commit lines and byte shares line up.
LANGUAGE_EXTENSIONS = {
    ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript", ".cts": "TypeScript",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".py": "Python", ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin", ".cs": "C#",
    ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++", ".hpp": "C++", ".swift": "Swift",
    ".css": "CSS", ".scss": "SCSS", ".html": "HTML", ".htm": "HTML", ".vue": "Vue", ".svelte": "Svelte",
    ".sh": "Shell", ".bash": "Shell", ".ps1": "PowerShell", ".bat": "Batchfile", ".cmd": "Batchfile",
    ".sql": "PLpgSQL", ".ejs": "EJS", ".php": "PHP", ".rb": "Ruby", ".dart": "Dart", ".lua": "Lua",
}
LANGUAGE_FILENAMES = {"Dockerfile": "Dockerfile", "Makefile": "Makefile"}
VENDORED = {"node_modules", "vendor", "dist", "build", ".next", "coverage"}


class CollectionError(RuntimeError):
    """A complete, trustworthy activity snapshot could not be collected."""


class Unavailable(CollectionError):
    """GitHub refused an endpoint for this token (401/403/404); callers may degrade gracefully."""


class NotFound(Unavailable):
    """GitHub answered 404 for an endpoint that some repositories do not expose."""


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

    def get(self, path_or_url: str, accept: str | None = None) -> tuple[Any, dict[str, str]]:
        url = path_or_url if path_or_url.startswith("https://") else API_ROOT + path_or_url
        # Never forward an authorization token to a foreign pagination host.
        if urlsplit(url).scheme != "https" or urlsplit(url).netloc != "api.github.com":
            raise CollectionError("Refusing a pagination URL outside api.github.com")
        headers = {
            "Accept": accept or "application/vnd.github+json",
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
                kind = NotFound if error.code == 404 else Unavailable if error.code in (401, 403) else CollectionError
                raise kind(f"GitHub API returned HTTP {error.code} for {url}.{detail}") from error
            except (URLError, TimeoutError) as error:
                if attempt < 2:
                    clock.sleep(2 ** (attempt + 1))
                    continue
                raise CollectionError(f"Could not reach GitHub API at {url}: {error}") from error
            except (ValueError, UnicodeError) as error:
                raise CollectionError(f"GitHub returned invalid JSON for {url}") from error
        raise AssertionError("Unreachable retry state")

    def pages(self, path: str, accept: str | None = None):
        seen_urls: set[str] = set()
        next_url: str | None = path
        while next_url:
            if next_url in seen_urls:
                raise CollectionError("GitHub pagination repeated a URL")
            seen_urls.add(next_url)
            values, headers = self.get(next_url, accept) if accept else self.get(next_url)
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

    def get(self, path_or_url: str, accept: str | None = None) -> tuple[Any, dict[str, str]]:
        path = path_or_url.removeprefix(API_ROOT)
        entry = self.responses.get(path, self.responses.get(API_ROOT + path))
        if not isinstance(entry, dict) or "body" not in entry:
            raise CollectionError(f"Replay is missing an API response: {path}")
        self.requests += 1
        return entry["body"], {key.lower(): value for key, value in entry.get("headers", {}).items()}


def collect_open_source(username: str, client: GitHubClient, exclusions: list[str] = ()) -> dict[str, Any]:
    """Count merged pull requests to repositories owned by other users/orgs."""
    query = " ".join([f"is:pr author:{username} is:merged -user:{username} is:public",
                      *(f"-repo:{name}" for name in exclusions)])
    excluded = {name.lower() for name in exclusions}
    repositories: dict[str, int] = {}
    merged_dates: dict[str, list[str]] = {}
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
            if repository.lower() in excluded:
                raise CollectionError(f"Open-source search ignored the exclusion for {repository}")
            if url in seen_urls:
                raise CollectionError("Open-source search duplicated a pull request; retry the refresh")
            try:
                merged_at = parse_datetime((item.get("pull_request") or {}).get("merged_at"))
            except (TypeError, AttributeError, ValueError) as error:
                raise CollectionError(f"Merged pull request has no merge time: {url}") from error
            seen_urls.add(url)
            repositories[repository] = repositories.get(repository, 0) + 1
            merged_dates.setdefault(repository, []).append(iso(merged_at))
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
        "repositories": [{"name": name, "merged_prs": count, "url": f"https://github.com/{name}",
                          "merged_at": sorted(merged_dates[name])}
                         for name, count in sorted(repositories.items(), key=lambda pair: (-pair[1], pair[0]))],
        "recent": recent,
        "recent_order": "Most recently updated merged pull requests",
        "query": query,
        "excluded_repositories": list(exclusions),
        "url": "https://github.com/search?" + urlencode({"q": query, "type": "pullrequests"}),
        "scope": "Public merged pull requests authored by the user in repositories they do not own; all time",
    }


def star_days(stargazers) -> dict[str, int]:
    days: dict[str, int] = {}
    for stargazer in stargazers:
        try:
            day = parse_datetime(stargazer["starred_at"]).date().isoformat()
        except (TypeError, KeyError, ValueError) as error:
            raise CollectionError("Stargazer without a star date") from error
        days[day] = days.get(day, 0) + 1
    return days


def collect_stars(targets: list[tuple[str, int]], client: GitHubClient,
                  previous: dict[str, Any] | None = None, today: str | None = None) -> dict[str, Any]:
    """Star dates per repository. Stargazers are listed oldest first, so a growing
    count only needs the newest pages; anything else triggers a full re-read.

    GitHub only lets user tokens list stargazers, and some repositories hide the list.
    When it is unavailable the count still comes from the repository itself, and new
    stars are dated on the day a refresh first sees them (within one refresh interval)."""
    known = {row["name"].lower(): row for row in (previous or {}).get("repositories", [])}
    result, observed = [], []
    for repository, count in targets:
        cached = known.get(repository.lower())
        if cached and cached["stars"] == count:
            result.append(cached)
            continue
        try:
            starred_on = None
            if cached and count > cached["stars"] and not cached.get("undated"):
                first_page = cached["stars"] // 100 + 1
                fresh = list(client.pages(f"/repos/{repository}/stargazers?per_page=100&page={first_page}", STAR_ACCEPT))
                starred_on = dict(cached["starred_on"])
                for day, number in star_days(fresh[cached["stars"] - (first_page - 1) * 100:]).items():
                    starred_on[day] = starred_on.get(day, 0) + number
                if sum(starred_on.values()) != count:
                    starred_on = None
            if starred_on is None:
                starred_on = star_days(client.pages(f"/repos/{repository}/stargazers?per_page=100", STAR_ACCEPT))
            result.append({"name": repository, "stars": sum(starred_on.values()),
                           "starred_on": dict(sorted(starred_on.items()))})
        except Unavailable:
            starred_on = dict(cached["starred_on"]) if cached else {}
            if cached and today and count > cached["stars"]:
                starred_on[today] = starred_on.get(today, 0) + count - cached["stars"]
                observed.append(repository)
            row = {"name": repository, "stars": count, "starred_on": dict(sorted(starred_on.items()))}
            if count != sum(starred_on.values()):
                row["undated"] = count - sum(starred_on.values())
            result.append(row)
    return {"total": sum(row["stars"] for row in result), "repositories": result,
            "dated_on_observation": observed,
            "scope": "Current stargazers of configured public owned repositories plus external repositories "
                     "with merged pull requests from the user (after configured exclusions)"}


def file_language(filename: str) -> str | None:
    name = filename.rsplit("/", 1)[-1]
    if name in LANGUAGE_FILENAMES:
        return LANGUAGE_FILENAMES[name]
    if any(part in VENDORED for part in filename.split("/")) or name.endswith((".min.js", ".min.css")):
        return None
    return LANGUAGE_EXTENSIONS.get(Path(name).suffix.lower())


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


def package_names(base: str, text: str) -> tuple[str, set[str]]:
    """Dependency names declared by one manifest, keyed by ecosystem."""
    def python_name(spec: str) -> str:
        match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", spec)
        return match.group(1).lower().replace("_", "-") if match else ""
    try:
        if base == "package.json":
            manifest = json.loads(text)
            return "npm", {name for field in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")
                           for name in (manifest.get(field) or {})}
        if base.startswith("requirements"):
            return "python", {python_name(line) for line in text.splitlines() if line.strip() and not line.lstrip().startswith(("#", "-"))}
        if base in ("pyproject.toml", "Pipfile", "Cargo.toml"):
            data = tomllib.loads(text)
            if base == "Cargo.toml":
                return "cargo", set(data.get("dependencies", {})) | set(data.get("dev-dependencies", {}))
            project = data.get("project", {})
            specs = list(project.get("dependencies", [])) + [spec for group in project.get("optional-dependencies", {}).values() for spec in group]
            names = {python_name(spec) for spec in specs} | set(data.get("packages", {})) | set(data.get("dev-packages", {}))
            names |= set(data.get("tool", {}).get("poetry", {}).get("dependencies", {}))
            return "python", {name.lower().replace("_", "-") for name in names}
    except (ValueError, TypeError, AttributeError, tomllib.TOMLDecodeError):
        pass
    return "", set()


def detect_stack(repository: str, branch: str, client: GitHubClient) -> list[str]:
    """Name the tools a repository uses, from its manifests, container files and layout."""
    tree, _ = client.get(f"/repos/{repository}/git/trees/{quote(branch, safe='')}?recursive=1")
    paths = [item.get("path", "") for item in tree.get("tree", []) if item.get("type") == "blob"]
    paths = [path for path in paths if not set(path.split("/")) & VENDORED]
    facts: dict[str, Any] = {"npm": set(), "python": set(), "cargo": set(), "go": "", "maven": "", "text": "",
                             "files": {path.rsplit("/", 1)[-1] for path in paths}, "paths": paths}
    for path in [path for path in paths if path.rsplit("/", 1)[-1] in catalog.MANIFESTS][:24]:
        body, _ = client.get(f"/repos/{repository}/contents/{quote(path)}?{urlencode({'ref': branch})}")
        try:
            text = base64.b64decode(body.get("content", "")).decode("utf-8", "replace")
        except (ValueError, TypeError) as error:
            raise CollectionError(f"Unreadable manifest {repository}/{path}") from error
        base = path.rsplit("/", 1)[-1]
        ecosystem, names = package_names(base, text)
        if ecosystem:
            facts[ecosystem] |= names
        elif base == "go.mod":
            facts["go"] += text
        elif base in ("pom.xml", "build.gradle", "build.gradle.kts"):
            facts["maven"] += text
        elif base not in ("package.json", "pyproject.toml", "Pipfile", "Cargo.toml") and not base.startswith("requirements"):
            facts["text"] += text.lower() + "\n"
    return sorted(name for name, rules in catalog.TOOLS.items() if catalog.tool_matches(rules, facts))


def fetch_logo(url: str) -> str | None:
    """Download a public SVG logo from jsDelivr; any failure just means "not found yet"."""
    if not url.startswith("https://cdn.jsdelivr.net/"):
        return None
    try:
        with urlopen(Request(url, headers={"User-Agent": "Economist-profile-activity"}), timeout=15) as response:
            body = response.read(200_000)
        text = body.decode("utf-8")
        return text if "<svg" in text else None
    except (OSError, ValueError, UnicodeError):
        return None


def clean_svg(markup: str, colour: str | None) -> str:
    markup = re.sub(r"(?is)<script.*?</script>|<title>.*?</title>|<\?xml.*?\?>|<!--.*?-->", "", markup)
    markup = re.sub(r"(?i)\son[a-z]+=\"[^\"]*\"", "", markup).strip()
    if colour:
        markup = re.sub(r"<svg\b", f'<svg fill="#{colour}"', markup, count=1)
    return markup


def resolve_logos(names: list[str], previous: dict[str, Any], today: str,
                  fetch: Callable[[str], str | None] | None) -> dict[str, Any]:
    """Logos for every language and tool without a vendored file, cached between runs."""
    logos: dict[str, Any] = {}
    for name in dict.fromkeys(names):
        if name in catalog.VENDORED:
            continue
        cached = previous.get(name)
        if cached and (cached.get("svg") or cached.get("checked") == today or fetch is None):
            logos[name] = cached
            continue
        found = None
        for url, colour in (catalog.logo_urls(name) if fetch else []):
            markup = fetch(url)
            if markup:
                found = {"svg": clean_svg(markup, colour), "source": url}
                break
        logos[name] = found or {"missing": True, "checked": today}
    return logos


def commit_detail(repository: str, sha: str, committed_at: datetime, client: GitHubClient) -> dict[str, Any]:
    detail, _ = client.get(f"/repos/{repository}/commits/{sha}")
    stats = detail.get("stats") or {}
    additions, deletions = stats.get("additions"), stats.get("deletions")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (additions, deletions)):
        raise CollectionError(f"Missing line statistics for {repository}/{sha}")
    files = detail.get("files") or []
    languages: dict[str, list[int]] = {}
    for changed in files:
        language = file_language(str(changed.get("filename", "")))
        if language:
            row = languages.setdefault(language, [0, 0])
            row[0] += int(changed.get("additions") or 0)
            row[1] += int(changed.get("deletions") or 0)
    # GitHub lists at most 300 files per commit response; the rest stays unattributed.
    return {"sha": sha, "repository": repository, "timestamp": iso(committed_at),
            "additions": additions, "deletions": deletions, "languages": languages,
            "files_truncated": len(files) >= 300, "url": f"https://github.com/{repository}/commit/{sha}"}


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
        previous = load_previous(args.output)
        snapshot = collect(config, client, now, lambda message: print(message, file=sys.stderr, flush=True), previous,
                           None if args.responses else fetch_logo)
        write_snapshot(args.output, snapshot)
    except (CollectionError, OSError, ValueError) as error:
        print(f"Activity refresh failed; previous snapshot preserved: {error}", file=sys.stderr)
        return 1
    coverage = snapshot["coverage"]
    print(f"Wrote {args.output}: {len(snapshot['commits'])} commits across {coverage['repository_count']} "
          f"public repositories ({coverage['reused_repositories']} unchanged); {coverage['api_requests']} API requests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
