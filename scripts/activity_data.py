"""Fetch an auditable, complete public commit tape for the market board.

Only Python's standard library is required. A failed API request leaves the last
successful output untouched. GITHUB_TOKEN is optional, but strongly recommended
because GitHub's unauthenticated API allowance is small.

Refreshes are incremental so they can run every few minutes: repositories whose
pushed_at did not move reuse the previous snapshot, commit statistics are cached
by SHA (they never change), and stargazer histories only fetch their newest pages."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys

from collector.github import (
    STAR_ACCEPT, UTC, CollectionError, GitHubClient, NotFound, ReplayClient, Unavailable, parse_datetime,
)
from collector.snapshot import build_weeks, collect, load_previous, validate_config, write_snapshot
from collector.sources import collect_open_source, collect_stars, detect_stack, fetch_logo, resolve_logos

__all__ = [
    "STAR_ACCEPT", "CollectionError", "GitHubClient", "NotFound", "ReplayClient", "Unavailable", "build_weeks", "collect",
    "collect_open_source", "collect_stars", "detect_stack", "fetch_logo", "load_previous", "main", "parse_datetime",
    "resolve_logos", "validate_config", "write_snapshot",
]


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
