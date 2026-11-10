"""Update the public collaborator list used by the stars index.

Run locally with your own GitHub account, and rerun after repository access changes:
    python scripts/sync_star_access.py

Uses GH_TOKEN / GITHUB_TOKEN, or the existing `gh auth` session. Only public
repository names and the verification time are saved; credentials remain local.
The regular Actions refresh uses this verified list without a personal token.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from urllib.parse import urlencode

from collector.github import CollectionError, GitHubClient, UTC, iso
from collector.snapshot import write_snapshot


def access_token() -> str:
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        token = os.environ.get(name, "").strip()
        if token:
            return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token", "--hostname", "github.com"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CollectionError("Sign in with gh auth login, or set GH_TOKEN for your own GitHub account") from error
    if result.returncode or not result.stdout.strip():
        raise CollectionError("Sign in with gh auth login, or set GH_TOKEN for your own GitHub account")
    return result.stdout.strip()


def discover_collaborators(username: str, client: GitHubClient) -> list[str]:
    """Public repositories outside the user's namespace where they can push."""
    if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", username):
        raise CollectionError("profile.json needs a valid github_username")
    identity, _ = client.get("/user")
    if not isinstance(identity, dict) or str(identity.get("login", "")).lower() != username.lower():
        raise CollectionError(f"The authenticated GitHub account must be {username}; profile.json was not changed")
    params = urlencode({"visibility": "public", "affiliation": "owner,collaborator,organization_member", "per_page": 100})
    repositories: dict[str, str] = {}
    for repository in client.pages("/user/repos?" + params):
        if not isinstance(repository, dict):
            raise CollectionError("GitHub returned an invalid repository in the access listing")
        if repository.get("private") is not False or repository.get("visibility", "public") != "public":
            continue
        permissions = repository.get("permissions") or {}
        if not isinstance(permissions, dict) or not any(permissions.get(role) is True for role in ("push", "maintain", "admin")):
            continue
        name = repository.get("full_name", "")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", name):
            raise CollectionError("GitHub returned an invalid repository name in the access listing")
        if name.split("/")[0].lower() == username.lower():
            continue
        repositories.setdefault(name.lower(), name)
    return sorted(repositories.values(), key=str.lower)


def sync_config(config: dict[str, Any], client: GitHubClient, now: datetime) -> dict[str, Any]:
    repositories = discover_collaborators(config.get("github_username", ""), client)
    return dict(config, star_collaborator_repositories=repositories, star_access_verified_at=iso(now))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("profile.json"))
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8-sig"))
        if not isinstance(config, dict):
            raise CollectionError("profile.json must contain an object")
        updated = sync_config(config, GitHubClient(access_token()), datetime.now(UTC))
        write_snapshot(args.config, updated)
    except (CollectionError, OSError, ValueError) as error:
        print(f"Access sync failed; previous configuration preserved: {error}", file=sys.stderr)
        return 1
    print(f"Verified {len(updated['star_collaborator_repositories'])} public collaborator repositories "
          f"for {updated['github_username']}; saved {args.config}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
