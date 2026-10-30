"""The GitHub REST client, its replay double for tests, and shared time helpers."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import time as clock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


UTC = timezone.utc


API_ROOT = "https://api.github.com"


STAR_ACCEPT = "application/vnd.github.star+json"


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
