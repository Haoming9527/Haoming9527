"""Render the brokerage-app profile: live SVG widgets, README.md and the other range views.

Every number comes from data/activity.json; profile.json supplies names, links, logos
and the curated achievements. Each widget is written in light/dark and desktop/phone
variants that GitHub picks between with <picture> media queries.

The D/W/M/Q/Y tabs are links. README.md is the weekly view; the other four are full
copies of the dashboard rendered for their range and published with the widgets on
the `market` branch. Choosing a tab therefore changes every number on the page."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from board.chart import candle_title
from board.market import VIEWS, Market, View
from board.pages import LIVE_BASE, build, check_config
from board.svg import ROOT
from board.widgets import RANGE_PCT, TAB_PCT

__all__ = ["LIVE_BASE", "RANGE_PCT", "ROOT", "TAB_PCT", "VIEWS", "Market", "View", "build", "candle_title", "check_config", "main"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/activity.json")
    parser.add_argument("--config", type=Path, default=ROOT / "profile.json")
    parser.add_argument("--output", type=Path, default=ROOT / "assets/gen")
    parser.add_argument("--views", type=Path, default=ROOT / "views")
    parser.add_argument("--base", default=LIVE_BASE, help="URL prefix for widget images")
    args = parser.parse_args()
    data = json.loads(args.data.read_text(encoding="utf-8"))
    config = json.loads(args.config.read_text(encoding="utf-8"))
    check_config(config)
    if not data["coverage"]["complete"] or data.get("schema_version", 1) < 3:
        raise ValueError("Refusing to render an incomplete or outdated activity snapshot")
    files, readme, pages, missing = build(data, config, args.base)
    args.output.mkdir(parents=True, exist_ok=True)
    args.views.mkdir(parents=True, exist_ok=True)
    # Both folders are fully generated; clearing them drops widgets that no longer exist.
    for stale in args.output.glob("*.svg"):
        if stale.name not in files:
            stale.unlink()
    for name, content in files.items():
        (args.output / name).write_text(content, encoding="utf-8", newline="\n")
    for code, content in pages.items():
        (args.views / f"{code}.md").write_text(content, encoding="utf-8", newline="\n")
    (ROOT / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    print(f"Rendered {len(files)} widgets, README.md and {len(pages)} range views.")
    if missing:
        note = "No logo found yet for: " + ", ".join(missing) + ". Add a file to assets/logos and map it in scripts/catalog.py."
        print(note)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
                summary.write(f"{note}\n")


if __name__ == "__main__":
    main()
