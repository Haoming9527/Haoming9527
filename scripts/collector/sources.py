"""Individual data sources: merged pull requests, stargazers, languages, tool detection and logos."""
from __future__ import annotations

import base64
from datetime import datetime
import json
from pathlib import Path
import re
import tomllib
from typing import Any, Callable
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import catalog

from .github import API_ROOT, CollectionError, GitHubClient, STAR_ACCEPT, Unavailable, iso, parse_datetime


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


def collect_open_source(username: str, client: GitHubClient, exclusions: list[str] = ()) -> dict[str, Any]:
    """Count every public merged pull request by the user. Repositories owned by others are listed
    separately because they also drive the Collaborations rows and the collaborators' stars."""
    query = " ".join([f"is:pr author:{username} is:merged is:public", *(f"-repo:{name}" for name in exclusions)])
    external_query = " ".join([f"is:pr author:{username} is:merged -user:{username} is:public",
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
    rows = [{"name": name, "merged_prs": count, "url": f"https://github.com/{name}", "merged_at": sorted(merged_dates[name])}
            for name, count in sorted(repositories.items(), key=lambda pair: (-pair[1], pair[0]))]
    mine = lambda row: row["name"].split("/")[0].lower() == username.lower()
    external = [row for row in rows if not mine(row)]
    return {
        "total_merged_prs": expected,
        "external_merged_prs": sum(row["merged_prs"] for row in external),
        "repository_count": len(external),
        "repositories": external,
        "owned_repositories": [row for row in rows if mine(row)],
        "recent": recent,
        "recent_order": "Most recently updated merged pull requests",
        "query": query,
        "excluded_repositories": list(exclusions),
        "url": "https://github.com/search?" + urlencode({"q": query, "type": "pullrequests"}),
        "external_url": "https://github.com/search?" + urlencode({"q": external_query, "type": "pullrequests"}),
        "scope": "Public merged pull requests authored by the user in any repository; all time. "
                 "repositories lists the ones owned by others, owned_repositories the user's own",
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
