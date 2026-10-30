"""Render the brokerage-app profile: live SVG widgets, README.md and the other range views.

Every number comes from data/activity.json; profile.json supplies names, links, logos
and the curated achievements. Each widget is written in light/dark and desktop/phone
variants that GitHub picks between with <picture> media queries.

The D/W/M/Q/Y tabs are links. README.md is the weekly view; the other four are full
copies of the dashboard rendered for their range and published with the widgets on
the `market` branch. Choosing a tab therefore changes every number on the page.
"""
from __future__ import annotations

import argparse
import base64
from datetime import date, datetime, timedelta
from functools import cached_property
from html import escape
import json
import math
import os
from pathlib import Path
import re

import catalog

ROOT = Path(__file__).resolve().parents[1]
LOGOS = ROOT / "assets/logos"
OWNER = "Haoming9527"
LIVE_BASE = f"https://raw.githubusercontent.com/{OWNER}/{OWNER}/market/"
BANNER_LIVE = f"https://raw.githubusercontent.com/{OWNER}/{OWNER}/main/assets/nyse-banner.png"
PROFILE_URL = f"https://github.com/{OWNER}"
VIEW_URL = f"https://github.com/{OWNER}/{OWNER}/blob/market/views/{{}}.md"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"
THEMES = {
    "light": dict(bg="#ffffff", card="#f6f8fa", fg="#1f2328", muted="#59636e", faint="#d8dee4",
                  grid="#eaeef2", up="#1a7f37", up_fill="#2da44e", down="#cf222e", down_fill="#e5484d",
                  flat="#8c959f", ring="#d0d7de", pill="#eaeef2", segment="#ffffff", new="#0969da",
                  ma=("#bf8700", "#8250df")),
    "dark": dict(bg="#0d1117", card="#151b23", fg="#f0f6fc", muted="#9198a1", faint="#2a313c",
                 grid="#1f2630", up="#3fb950", up_fill="#2ea043", down="#f85149", down_fill="#da3633",
                 flat="#6e7681", ring="#0d1117", pill="#262c36", segment="#3b434f", new="#1f6feb",
                 ma=("#e3b341", "#a371f7")),
}
MA_PERIODS = (5, 10)   # moving averages drawn once a view has at least MA_MINIMUM candles
MA_MINIMUM = 12
# code: (name, days behind every change figure, change label)
VIEWS = {"D": ("Daily", 1, "1D"), "W": ("Weekly", 7, "7D"), "M": ("Monthly", 30, "1M"),
         "Q": ("Quarterly", 91, "3M"), "Y": ("Yearly", 365, "1Y")}
DEFAULT_VIEW = "W"
MINUS = "\u2212"
VISIBLE_LANGUAGES = 6
VISIBLE_TOOLS = 8
GENERIC_LOGO = "M8 7 L3 12 L8 17 M16 7 L21 12 L16 17 M14 5 L10 19"


# ---------------------------------------------------------------- formatting

def num(value: float) -> str:
    return (MINUS if value < 0 else "") + f"{abs(round(value)):,}"


def compact(value: float) -> str:
    sign, value = (MINUS if value < 0 else ""), abs(value)
    if value >= 1_000_000:
        return f"{sign}{value / 1_000_000:.1f}m"
    if value >= 10_000:
        return f"{sign}{value / 1000:.1f}k"
    return f"{sign}{round(value):,}"


def kilo(value: float) -> str:
    return f"{value / 1000:.1f}k" if abs(value) >= 1000 else f"{round(value)}"


def signed(value: float, short: bool = False) -> str:
    if not value:
        return "0"
    return ("+" if value > 0 else MINUS) + (compact(abs(value)) if short else f"{abs(round(value)):,}")


def percent(delta: float, base: float) -> str:
    if not base:
        return ""
    value = delta / abs(base) * 100
    return ("+" if value > 0 else MINUS if value < 0 else "") + f"{abs(value):.2f}%"


def size_label(size: int) -> str:
    return f"{size / 1_048_576:.1f} MB" if size >= 1_048_576 else f"{max(size / 1024, .1):.0f} KB"


def text_width(value: str, size: float, weight: int = 400) -> float:
    """Generous width estimate for system sans fonts, used only for layout."""
    width = 0.0
    for char in value:
        if char == " ":
            width += .28
        elif char in ".,:;'|!il":
            width += .3
        elif char.isdigit():
            width += .6
        elif char.isupper() or char in "%&@MW":
            width += .68
        elif char.isascii():
            width += .54
        else:
            width += .8
    return width * size * (1.06 if weight >= 600 else 1)


def fit(value: str, size: float, room: float, weight: int = 400) -> str:
    if text_width(value, size, weight) <= room:
        return value
    while value and text_width(value + "…", size, weight) > room:
        value = value[:-1]
    return value.rstrip() + "…"


def wrap(value: str, size: float, room: float, weight: int = 400) -> list[str]:
    lines, line = [], ""
    for word in value.split():
        candidate = f"{line} {word}".strip()
        if line and text_width(candidate, size, weight) > room:
            lines.append(line)
            line = word
        else:
            line = candidate
    return lines + [line] if line else lines


def tone(value: float) -> str:
    return "up" if value > 0 else "down" if value < 0 else "flat"


def ago(delta: timedelta) -> str:
    """Rounded to hours and days, so the status widget changes at most once an hour."""
    minutes = max(delta.total_seconds(), 0) / 60
    if minutes < 60:
        return "<1h ago"
    if minutes < 24 * 60:
        return f"{int(minutes // 60)}h ago"
    return f"{int(minutes // 1440)}d ago"


def change_badge(change: float, start: float, first: date | None, since: date) -> tuple[str, str | None]:
    """Percentage move over the range, or NEW for something that only started inside it."""
    if first is not None and first > since and change:
        return "NEW", "new"
    if not start:
        return "0.00%", None
    return percent(change, start) or "0.00%", None


# ---------------------------------------------------------------- SVG writer

class SVG:
    def __init__(self, width: float, height: float, theme: str, label: str, extra_css: str = ""):
        self.w, self.h, self.theme, self.p = width, height, theme, THEMES[theme]
        self.uid = 0
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}" height="{height:g}" '
            f'viewBox="0 0 {width:g} {height:g}" role="img" aria-label="{escape(label)}">',
            f'<style>text{{font-family:{FONT};font-variant-numeric:tabular-nums}}'
            '.draw{stroke-dasharray:1;animation:draw 1.4s cubic-bezier(.3,.7,.2,1) both}'
            '@keyframes draw{from{stroke-dashoffset:1}to{stroke-dashoffset:0}}'
            '.pulse{transform-box:fill-box;transform-origin:center;animation:pulse 2.6s ease-out infinite}'
            '@keyframes pulse{0%{transform:scale(1);opacity:.55}80%,100%{transform:scale(3.2);opacity:0}}'
            f'{extra_css}'
            '@media (prefers-reduced-motion:reduce){*{animation:none!important}}</style>',
        ]
        self.rect(0, 0, width, height, "bg")

    def color(self, value: str) -> str:
        return self.p.get(value, value)

    def add(self, markup: str):
        self.parts.append(markup)

    def next_id(self) -> str:
        self.uid += 1
        return f"u{self.uid}"

    def rect(self, x, y, w, h, fill, r=0, **attrs):
        extra = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in attrs.items())
        self.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" height="{max(h, 0):.1f}" rx="{r:g}" '
                 f'fill="{self.color(fill)}"{extra}/>')

    def text(self, x, y, value, size=16, fill="fg", weight=400, anchor="start", **attrs):
        extra = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in attrs.items())
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size:g}" font-weight="{weight}" '
                 f'fill="{self.color(fill)}" text-anchor="{anchor}"{extra}>{escape(str(value))}</text>')

    def line(self, x1, y1, x2, y2, stroke="faint", width=1, **attrs):
        extra = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in attrs.items())
        self.add(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                 f'stroke="{self.color(stroke)}" stroke-width="{width:g}"{extra}/>')

    def sparkline(self, values, x, y, w, h, stroke, fill=True, dot=True, width=2, baseline=True):
        values = list(values) or [0]
        if len(values) == 1:
            values *= 2
        lo, hi = min(values), max(values)
        span = hi - lo
        points = [(x + i / (len(values) - 1) * w, y + h / 2 if not span else y + h - (v - lo) / span * h)
                  for i, v in enumerate(values)]
        path = "M" + " L".join(f"{px:.1f} {py:.1f}" for px, py in points)
        color = self.color(stroke)
        if baseline and span:
            # Dotted "previous close": where the range started, as in stock apps' mini charts.
            self.line(x, points[0][1], x + w, points[0][1], "muted", 1, stroke_dasharray="1.5 3", opacity=".6")
        if fill:
            gid = self.next_id()
            self.add(f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
                     f'<stop offset="0" stop-color="{color}" stop-opacity=".16"/>'
                     f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>')
            self.add(f'<path d="{path} L{x + w:.1f} {y + h:.1f} L{x:.1f} {y + h:.1f} Z" fill="url(#{gid})"/>')
        self.add(f'<path class="draw" pathLength="1" d="{path}" fill="none" stroke="{color}" '
                 f'stroke-width="{width:g}" stroke-linejoin="round" stroke-linecap="round"/>')
        if dot:
            px, py = points[-1]
            self.add(f'<circle class="pulse" cx="{px:.1f}" cy="{py:.1f}" r="3" fill="{color}"/>'
                     f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="{color}"/>')

    def image(self, filename: str, x, y, w, h, aspect="xMidYMid meet", clip: str | None = None):
        source = LOGOS / filename
        mime = "image/png" if source.suffix == ".png" else "image/jpeg"
        data = base64.b64encode(source.read_bytes()).decode()
        clip_attr = f' clip-path="url(#{clip})"' if clip else ""
        self.add(f'<image href="data:{mime};base64,{data}" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
                 f'preserveAspectRatio="{aspect}"{clip_attr}/>')

    def vector(self, markup: str, x, y, side):
        view_box = re.search(r'viewBox="([^"]+)"', markup)
        attrs = re.search(r"<svg\b([^>]*)>", markup)
        fill = re.search(r'\sfill="([^"]+)"', attrs.group(1)) if attrs else None
        inner = re.sub(r"(?s)^.*?<svg[^>]*>|</svg>\s*$|<title>.*?</title>", "", markup)
        prefix = self.next_id()
        inner = re.sub(r'id="([^"]+)"', lambda m: f'id="{prefix}{m.group(1)}"', inner)
        inner = re.sub(r"url\(#([^)]+)\)", lambda m: f"url(#{prefix}{m.group(1)})", inner)
        fill_attr = f' fill="{fill.group(1)}"' if fill and fill.group(1) != "currentColor" else ""
        self.add(f'<svg x="{x:.1f}" y="{y:.1f}" width="{side:.1f}" height="{side:.1f}" '
                 f'viewBox="{view_box.group(1) if view_box else "0 0 24 24"}"{fill_attr}>{inner}</svg>')

    def logo(self, cx, cy, r, spec: dict, square: bool = False):
        """A real logo in a white disc (or rounded tile), the way brokerage apps show tickers."""
        clip = self.next_id()
        shape = (f'<rect x="{cx - r:.1f}" y="{cy - r:.1f}" width="{2 * r:.1f}" height="{2 * r:.1f}" rx="{r * .32:.1f}"'
                 if square else f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:g}"')
        self.add(f'{shape} fill="#ffffff" stroke="{self.color("ring")}" stroke-width="1"/>'
                 f'<clipPath id="{clip}">{shape}/></clipPath>')
        scale = spec.get("scale", .6)
        if "file" in spec and not spec["file"].endswith(".svg"):
            cover = spec.get("fit") == "cover"
            side = 2 * r if cover else 2 * r * scale
            self.image(spec["file"], cx - side / 2, cy - side / 2, side, side,
                       "xMidYMid slice" if cover else "xMidYMid meet", clip)
        elif "file" in spec or "svg" in spec:
            markup = spec["svg"] if "svg" in spec else (LOGOS / spec["file"]).read_text(encoding="utf-8")
            side = 2 * r * scale
            self.vector(markup, cx - side / 2, cy - side / 2, side)
        else:
            side = 2 * r * .56
            self.add(f'<path d="{GENERIC_LOGO}" transform="translate({cx - side / 2:.1f} {cy - side / 2:.1f}) '
                     f'scale({side / 24:.3f})" fill="none" stroke="#59636e" stroke-width="2.2" '
                     'stroke-linecap="round" stroke-linejoin="round"/>')

    def chevron(self, x, y, size=9, stroke="muted"):
        self.add(f'<path d="M{x:.1f} {y - size:.1f} L{x + size * .62:.1f} {y:.1f} L{x:.1f} {y + size:.1f}" fill="none" '
                 f'stroke="{self.color(stroke)}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>')

    def badge(self, x, y, w, h, value: float, label: str, size: float, fill: str | None = None):
        fill = fill or ("up_fill" if value > 0 else "down_fill" if value < 0 else "flat")
        self.rect(x, y, w, h, fill, 6)
        self.text(x + w / 2, y + h / 2 + size * .36, fit(label, size, w - 8, 700), size, "#ffffff", 700, "middle")

    def svg(self) -> str:
        return "\n".join(self.parts + ["</svg>"]) + "\n"


# ---------------------------------------------------------------- derived data

def month_start(when: date, offset: int = 0) -> date:
    index = when.year * 12 + when.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def periods(code: str, first: date, today: date) -> list[tuple[date, date]]:
    if code == "D":
        return [(today - timedelta(days=29 - i),) * 2 for i in range(30)]
    if code == "W":
        monday = today - timedelta(days=today.weekday())
        return [(monday - timedelta(weeks=25 - i), monday - timedelta(weeks=25 - i) + timedelta(days=6)) for i in range(26)]
    span, count = {"M": (1, 24), "Q": (3, 12), "Y": (12, 8)}[code]

    def floor(when: date) -> date:
        index = when.year * 12 + when.month - 1
        index -= index % span
        return date(index // 12, index % 12 + 1, 1)
    current, start = floor(today), floor(first)
    starts = []
    while current >= start and len(starts) < count:
        starts.insert(0, current)
        current = month_start(current, -span)
    return [(begin, month_start(begin, span) - timedelta(days=1)) for begin in starts]


def period_label(code: str, begin: date, long: bool = False) -> str:
    if code == "D":
        return f"{begin:%a %d %b %Y}" if long else f"{begin:%b} {begin.day}"
    if code == "W":
        return f"Week of {begin:%d %b %Y}" if long else f"{begin:%b} {begin.day}"
    if code == "M":
        return f"{begin:%B %Y}" if long else (f"{begin:%b} '{begin:%y}" if begin.month == 1 else f"{begin:%b}")
    if code == "Q":
        return f"Q{(begin.month - 1) // 3 + 1} {begin.year}" if long else f"Q{(begin.month - 1) // 3 + 1} '{begin:%y}"
    return str(begin.year)


def add(events: dict, when: date, value: float = 1):
    events[when] = events.get(when, 0) + value


class Market:
    """Everything derived from one snapshot that does not depend on the selected range."""

    def __init__(self, data: dict, config: dict):
        self.data, self.config = data, config
        self.username = data["github_username"]
        self.offset = timedelta(hours=config.get("utc_offset_hours", 0))
        self.today = self.local(data["generated_at"])
        self.commits = sorted(data["commits"], key=lambda row: (row["timestamp"], row["sha"]))
        for row in self.commits:
            row["day"] = self.local(row["timestamp"])
        self.first = self.commits[0]["day"] if self.commits else self.today
        self.lines = sum(row["additions"] - row["deletions"] for row in self.commits)
        self.now = datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00"))
        self.last_commit = (datetime.fromisoformat(self.commits[-1]["timestamp"].replace("Z", "+00:00"))
                            if self.commits else None)
        self.timezone = config.get("timezone_label", "UTC")
        self.open_source = data["open_source"]
        sizes = data["languages"]["bytes"]
        self.language_total = sum(sizes.values()) or 1
        self.languages = list(sizes.items())
        stack = data.get("stack", {})
        self.tools = sorted(stack, key=lambda tool: (-len(self.stack_events(tool)), -len(stack[tool]), tool))

    def local(self, stamp: str) -> date:
        return (datetime.fromisoformat(stamp.replace("Z", "+00:00")) + self.offset).date()

    def events(self, kind: str, key: str = "") -> dict[date, float]:
        """Dated increments for one series: commits, lines, stars, PRs, a language or a tool."""
        result: dict[date, float] = {}
        if kind == "commits":
            for row in self.commits:
                add(result, row["day"])
        elif kind == "repo-lines":
            for row in self.commits:
                if row["repository"].lower() == key.lower():
                    add(result, row["day"], row["additions"] - row["deletions"])
        elif kind == "language":
            for row in self.commits:
                added, deleted = row.get("languages", {}).get(key, (0, 0))
                if added or deleted:
                    add(result, row["day"], added - deleted)
        elif kind == "stars":
            for repo in self.data["stars"]["repositories"]:
                for when, count in repo["starred_on"].items():
                    add(result, date.fromisoformat(when), count)
        elif kind == "prs":
            for repo in self.open_source["repositories"]:
                if not key or repo["name"].lower() == key.lower():
                    for stamp in repo["merged_at"]:
                        add(result, self.local(stamp))
        return result

    def stack_events(self, tool: str) -> dict[date, float]:
        repos = {name.lower() for name in self.data.get("stack", {}).get(tool, [])}
        result: dict[date, float] = {}
        for row in self.commits:
            if row["repository"].lower() in repos:
                add(result, row["day"])
        return result

    def undated_stars(self) -> int:
        return sum(repo.get("undated", 0) for repo in self.data["stars"]["repositories"])

    def stars_of(self, repository: str) -> int:
        return next((row["stars"] for row in self.data["stars"]["repositories"]
                     if row["name"].lower() == repository.lower()), 0)

    def logo(self, name: str) -> dict:
        if name in catalog.VENDORED:
            filename, scale = catalog.VENDORED[name]
            return {"file": filename, "scale": scale}
        cached = self.data.get("logos", {}).get(name, {})
        return {"svg": cached["svg"], "scale": .58} if cached.get("svg") else {}

    def missing_logos(self) -> list[str]:
        names = [name for name, _ in self.languages] + self.tools
        return [name for name in names if not self.logo(name)]


class View:
    """One tab: candle size, the trailing window behind every change, and the series on its axis."""

    def __init__(self, market: Market, code: str):
        self.market, self.code = market, code
        self.name, self.days, self.label = VIEWS[code]
        self.periods = periods(code, market.first, market.today)
        self.prefix = code.lower()

    @cached_property
    def candles(self) -> list[dict]:
        rows = self.market.commits
        first_day = self.periods[0][0]
        index = sum(row["additions"] - row["deletions"] for row in rows if row["day"] < first_day)
        result = []
        for begin, end in self.periods:
            candle = {"start": begin, "end": end, "open": index, "high": index, "low": index, "close": index,
                      "additions": 0, "deletions": 0, "commits": 0, "current": begin <= self.market.today <= end}
            for row in rows:
                if begin <= row["day"] <= end:
                    index += row["additions"]
                    candle["high"] = max(candle["high"], index)
                    index -= row["deletions"]
                    candle["low"] = min(candle["low"], index)
                    candle["additions"] += row["additions"]
                    candle["deletions"] += row["deletions"]
                    candle["commits"] += 1
            candle["close"] = index
            result.append(candle)
        return result

    def series(self, events: dict[date, float], base: float = 0) -> list[float]:
        """Cumulative value just before the first candle and at the end of every candle."""
        cutoffs = [self.periods[0][0] - timedelta(days=1)] + [min(end, self.market.today) for _, end in self.periods]
        ordered = sorted(events.items())
        values, total, cursor = [], base, 0
        for cutoff in cutoffs:
            while cursor < len(ordered) and ordered[cursor][0] <= cutoff:
                total += ordered[cursor][1]
                cursor += 1
            values.append(total)
        return values

    def change(self, events: dict[date, float]) -> float:
        since = self.market.today - timedelta(days=self.days)
        return sum(value for when, value in events.items() if since < when <= self.market.today)

    @cached_property
    def lines_change(self) -> float:
        """Net lines over this range: the headline change, which also colours the price tag."""
        return self.range_stats["close"] - self.range_stats["open"]

    @cached_property
    def since(self) -> date:
        return self.market.today - timedelta(days=self.days)

    @cached_property
    def range_stats(self) -> dict:
        """Key stats for the selected range, with the candles' additions-first rule for high and low."""
        index = sum(row["additions"] - row["deletions"] for row in self.market.commits if row["day"] <= self.since)
        stats = {"open": index, "high": index, "low": index, "vol": 0, "added": 0, "deleted": 0}
        for row in self.market.commits:
            if self.since < row["day"] <= self.market.today:
                index += row["additions"]
                stats["high"] = max(stats["high"], index)
                index -= row["deletions"]
                stats["low"] = min(stats["low"], index)
                stats["vol"] += 1
                stats["added"] += row["additions"]
                stats["deleted"] += row["deletions"]
        stats["close"] = index
        return stats

    @cached_property
    def moving_averages(self) -> list[list[float | None]]:
        """MA5 and MA10 of candle closes; empty for views too short to make them meaningful."""
        closes = [candle["close"] for candle in self.candles]
        if len(closes) < MA_MINIMUM:
            return []
        return [[None if i + 1 < k else sum(closes[i + 1 - k:i + 1]) / k for i in range(len(closes))]
                for k in MA_PERIODS]

    def badge(self, events: dict[date, float], base: float = 0) -> tuple[float, str, str | None]:
        """(change, label, fill) for a percentage badge over this range."""
        change = self.change(events)
        start = base + sum(value for when, value in events.items() if when <= self.since)
        label, fill = change_badge(change, start, min(events) if events else None, self.since)
        return change, label, fill

    def index(self, key: str) -> dict:
        events = self.market.events(key)
        base = self.market.undated_stars() if key == "stars" else 0
        value = base + sum(events.values())
        delta = self.change(events)
        return {"series": self.series(events, base), "value": value, "delta": delta, "previous": value - delta}


# ---------------------------------------------------------------- widgets

def tape(view: View, theme: str, mobile: bool) -> SVG:
    market = view.market
    w, h, size = (400, 46, 17) if mobile else (846, 40, 14)
    items = [("ECON", market.config["role"], "", "none")]
    for key, label in (("stars", "STARS"), ("commits", "COMMITS"), ("prs", "MERGED PRS")):
        index = view.index(key)
        items.append((label, num(index["value"]), signed(index["delta"]), tone(index["delta"])))
    since = market.today - timedelta(days=view.days)
    lines = sum(row["additions"] - row["deletions"] for row in market.commits if row["day"] > since)
    items.append(("LINES", num(market.lines), signed(lines), tone(lines)))
    for name, size_bytes in market.languages[:4]:
        recent = view.change(market.events("language", name))
        items.append((name.upper(), f"{size_bytes / market.language_total * 100:.1f}%", signed(recent, True), tone(recent)))
    for project in market.config["projects"]:
        events = market.events("repo-lines", project["repository"])
        recent = view.change(events)
        items.append((project["ticker"], num(sum(events.values())), signed(recent, True), tone(recent)))
    pieces, x = [], 0.0
    for label, value, change, direction in items:
        pieces.append((x, label, value, change, direction))
        x += sum(text_width(part, size, 600) for part in (label, value, change)) + size * 4.4
    loop, duration = x, x / (30 if mobile else 38)
    s = SVG(w, h, theme, "Live tape of the profile indexes",
            f'.run{{animation:run {duration:.0f}s linear infinite}}@keyframes run{{to{{transform:translateX(-{loop:.1f}px)}}}}')
    s.line(0, .5, w, .5, "faint")
    s.line(0, h - .5, w, h - .5, "faint")
    s.add('<g class="run">')
    baseline = h / 2 + size * .36
    for offset in (0, loop):
        for i, (px, label, value, change, direction) in enumerate(pieces):
            px += offset + size
            if i:
                s.line(px - size * 1.6, h * .3, px - size * 1.6, h * .7, "faint", 1)
            else:
                # The profile's own symbol sits in a chip, like a ticker badge.
                s.rect(px - size * .45, h / 2 - size * .82, text_width(label, size, 600) + size * .9, size * 1.64, "pill", 4)
            s.text(px, baseline, label, size, "muted" if i else "fg", 600)
            px += text_width(label, size, 600) + size * .6
            s.text(px, baseline, value, size, "fg", 600)
            if direction != "none":
                px += text_width(value, size, 600) + size * .6
                arrow = "▲" if direction == "up" else "▼" if direction == "down" else "■"
                s.text(px, baseline, f"{arrow} {change}", size, direction, 600)
    s.add("</g>")
    return s


TAB_PCT, STATUS_PCT = 11.0, 44.6


def tab(code: str, active: bool, theme: str, mobile: bool) -> SVG:
    """One segment of the D/W/M/Q/Y control. The five images sit edge to edge, so each
    draws its slice of a single track: only the outer ends are rounded."""
    unit = 4.0 if mobile else 8.46
    w, h = TAB_PCT * unit, (40 if mobile else 44)
    s = SVG(w, h, theme, f"{VIEWS[code][0]} view")
    order = list(VIEWS)
    track_y, track_h = 4, h - 8
    left = 1 if code == order[0] else -track_h
    right = w - 1 if code == order[-1] else w + track_h
    s.rect(left, track_y, right - left, track_h, "pill", track_h / 2)
    if active:
        s.rect(3, track_y + 3, w - 6, track_h - 6, "segment", (track_h - 6) / 2, stroke=s.color("faint"), stroke_width=1)
    size = 17 if mobile else 15
    s.text(w / 2, h / 2 + size * .36, code, size, "fg" if active else "muted", 700 if active else 600, "middle")
    return s


def market_status(view: View, theme: str, mobile: bool) -> SVG:
    """Right of the tabs: when the last commit landed, and the window behind every change."""
    market = view.market
    unit = 4.0 if mobile else 8.46
    w, h = STATUS_PCT * unit, (40 if mobile else 44)
    when = market.last_commit
    since = ago(market.now - when) if when else "no commits yet"
    local = f"{(when + market.offset):%d %b, %H:%M} {market.timezone}" if when else ""
    s = SVG(w, h, theme, f"Last commit {since} ({local}); changes over {view.label}")
    size = 15 if mobile else 13
    note = view.label if mobile else f"{view.label} change"
    y = h / 2 + size * .36
    s.text(w - 4, y, note, size, "muted", 500, "end")
    status = since if mobile else f"Last commit {since}"
    x = w - 4 - text_width(note, size, 500) - 14
    s.text(x, y, status, size, "fg", 600, "end")
    dot_x = x - text_width(status, size, 600) - 10
    open_market = bool(when) and (market.now - when) < timedelta(hours=24)
    color = s.color("up" if open_market else "flat")
    if open_market:
        s.add(f'<circle class="pulse" cx="{dot_x:.1f}" cy="{h / 2:.1f}" r="3.5" fill="{color}"/>')
    s.add(f'<circle cx="{dot_x:.1f}" cy="{h / 2:.1f}" r="3.5" fill="{color}"/>')
    return s


INDEX_TILES = (("stars", "Stars", "mine + collab"), ("commits", "Commits", "all time"), ("prs", "Merged PRs", "external"))


TICK_CSS = ".tick{animation:tick 1.8s ease-out .3s both}@keyframes tick{0%{opacity:0}12%{opacity:1}100%{opacity:0}}"


def flash(s: SVG, x: float, baseline: float, text_w: float, size: float, direction: str):
    """A one-off highlight behind a value when the image loads, like a live price tick."""
    if direction != "flat":
        s.rect(x - size * .18, baseline - size * .9, text_w + size * .36, size * 1.16, direction, size * .2,
               opacity="0", fill_opacity=".18", **{"class": "tick"})


def index_tile(view: View, key: str, theme: str, mobile: bool) -> SVG:
    title, hint = next((title, hint) for k, title, hint in INDEX_TILES if k == key)
    index = view.index(key)
    color = tone(index["delta"])
    w, h = (200, 214) if mobile else (282, 178)
    s = SVG(w, h, theme, f"{title} index", TICK_CSS)
    s.rect(4, 4, w - 8, h - 8, "card", 16 if mobile else 14)
    x = 20 if mobile else 22
    change = f"{signed(index['delta'])} {percent(index['delta'], index['previous'])}".strip()
    value = num(index["value"])
    if mobile:
        s.text(x, 44, title, 22, "fg", 500)
        flash(s, x, 90, text_width(value, 36, 700), 36, color)
        s.text(x, 90, value, 36, color, 700)
        s.text(x, 122, change, 19, color, 500)
        s.sparkline(index["series"], x, 140, w - 2 * x, 46, color)
    else:
        s.text(x, 38, title, 18, "fg", 500)
        s.text(w - x, 38, hint, 12, "muted", 500, "end")
        flash(s, x, 78, text_width(value, 32, 700), 32, color)
        s.text(x, 78, value, 32, color, 700)
        s.text(x, 104, f"{change}  {view.label}", 14, color, 500)
        s.sparkline(index["series"], x, 118, w - 2 * x, 40, color)
    return s


def legend(s: SVG, view: View, x: float, y: float, size: float, ohlc: bool = True, averages: bool = True):
    """Latest candle O/H/L/C and moving averages, in the style of a trading app's chart legend."""
    candle = view.candles[-1]
    items = [(label, compact(candle[key]), "muted", "fg") for label, key in
             (("O", "open"), ("H", "high"), ("L", "low"), ("C", "close"))] if ohlc else []
    if averages:
        for k, values, color in zip(MA_PERIODS, view.moving_averages, s.p["ma"]):
            if values[-1] is not None:
                items.append((f"MA{k}", compact(values[-1]), color, color))
    for label, value, label_color, value_color in items:
        s.text(x, y, label, size, label_color, 500)
        x += text_width(label, size, 500) + size * .4
        s.text(x, y, value, size, value_color, 600)
        x += text_width(value, size, 600) + size * 1.2


def lines_header(view: View, theme: str, mobile: bool) -> SVG:
    """A stock-detail header: price and range change, key stats for the range, and the chart legend."""
    market, stats, change = view.market, view.range_stats, view.lines_change
    w, h = (400, 248) if mobile else (846, 132)
    s = SVG(w, h, theme, "Lines index: net lines of code I have added across my public repositories", TICK_CSS)
    pad = 18 if mobile else 24
    title_size = 22 if mobile else 18
    title_y = 34 if mobile else 30
    s.text(pad, title_y, "Lines index", title_size, "fg", 600)
    s.text(pad + text_width("Lines index", title_size, 600) + 10, title_y, f"since {market.first:%b %Y}",
           15 if mobile else 13, "muted", 500)
    value_size, value_y = (38, 80) if mobile else (32, 76)
    price = num(market.lines)
    flash(s, pad, value_y, text_width(price, value_size, 700), value_size, tone(change))
    s.text(pad, value_y, price, value_size, "fg", 700)
    change_text = f"{signed(change)} {percent(change, stats['open'])} {view.label}".replace("  ", " ")
    cells = (("Open", compact(stats["open"])), ("High", compact(stats["high"])), ("Low", compact(stats["low"])),
             ("Vol", f"{stats['vol']:,}"), ("Added", f"+{compact(stats['added'])}"),
             ("Deleted", f"{MINUS}{compact(stats['deleted'])}" if stats["deleted"] else "0"))
    if mobile:
        s.text(pad, 110, change_text, 17, tone(change), 600)
        left, cell_w, rows, label_size, value_size2 = pad, (w - 2 * pad) / 3, (146, 172), 14, 15
    else:
        s.text(pad + text_width(price, value_size, 700) + 14, value_y, change_text, 16, tone(change), 500)
        left, cell_w, rows, label_size, value_size2 = 456, (w - pad - 456) / 3, (50, 76), 12, 14
    for i, (label, value) in enumerate(cells):
        x, y = left + (i % 3) * cell_w, rows[i // 3]
        s.text(x, y, label, label_size, "muted", 500)
        s.text(x + cell_w - 14, y, value, value_size2, "fg", 600, "end")
    divider = 190 if mobile else 96
    s.line(pad, divider, w - pad, divider, "faint")
    if mobile:
        legend(s, view, pad, 214, 13, averages=False)
        legend(s, view, pad, 236, 13, ohlc=False)
    else:
        legend(s, view, pad, 118, 12)
    return s


# ---------------------------------------------------------------- candle chart

AXIS_PCT = 14.0


class Geometry:
    def __init__(self, candles: list[dict], mobile: bool):
        self.candles, self.n, self.mobile = candles, len(candles), mobile
        self.slice_pct = round((99.6 - AXIS_PCT) / self.n, 3)
        unit = 4.0 if mobile else 8.46            # canvas units per percent of README width
        self.slice_w, self.axis_w, self.full_w = self.slice_pct * unit, AXIS_PCT * unit, 100 * unit
        if mobile:
            self.h, self.top, self.bottom, self.vol_top, self.vol_bottom = 440, 24, 318, 344, 428
        else:
            self.h, self.top, self.bottom, self.vol_top, self.vol_bottom = 330, 22, 236, 256, 322
        values = [candle[k] for candle in candles for k in ("high", "low")]
        lo, hi = min(values), max(values)
        span = max(hi - lo, 10)
        power = 10 ** math.floor(math.log10(span / 4))
        self.step = next(n * power for n in (1, 2, 2.5, 5, 10) if n * power >= span / 4)
        self.lo, self.hi = lo - span * .06, hi + span * .12
        self.max_commits = max([candle["commits"] for candle in candles] + [1])
        self.high_index = max(range(self.n), key=lambda i: candles[i]["high"])
        self.low_index = min(range(self.n), key=lambda i: candles[i]["low"])
        self.body = min(self.slice_w * .62, 30 if mobile else 26)

    def y(self, value: float) -> float:
        return self.bottom - (value - self.lo) / (self.hi - self.lo) * (self.bottom - self.top)

    def ticks(self):
        return [k * self.step for k in range(math.ceil(self.lo / self.step), math.floor(self.hi / self.step) + 1)]


def direction(candle: dict) -> str:
    if not candle["commits"]:
        return "flat"
    return "down" if candle["close"] < candle["open"] else "up"


def candle_title(code: str, candle: dict) -> str:
    label = period_label(code, candle["start"], True)
    if candle["current"]:
        return f"{label}, in progress (updates live)"
    if not candle["commits"]:
        return f"{label}: no commits; index {num(candle['close'])}"
    return (f"{label}: {candle['commits']} commit{'s' if candle['commits'] != 1 else ''}, "
            f"+{candle['additions']:,} / {MINUS}{candle['deletions']:,} lines; open {num(candle['open'])}, "
            f"high {num(candle['high'])}, low {num(candle['low'])}, close {num(candle['close'])}")


def date_labels(view: View, mobile: bool) -> dict[int, str]:
    """Which candles get a date under them (shared by the date strip and the vertical gridlines)."""
    g = Geometry(view.candles, mobile)
    size = 15 if mobile else 11
    labels = [period_label(view.code, candle["start"]) for candle in view.candles]
    widest = max(text_width(label, size, 500) for label in labels) + (10 if mobile else 14)
    step = max(1, math.ceil(widest / g.slice_w))
    chosen = {}
    for i in range(g.n - 1, -1, -step):
        if (i + .5) * g.slice_w - text_width(labels[i], size, 500) / 2 >= 0:
            chosen[i] = labels[i]
    return chosen


def chart_slice(view: View, index: int, theme: str, mobile: bool) -> SVG:
    candles = view.candles
    g = Geometry(candles, mobile)
    candle, w = candles[index], g.slice_w
    delay = index * min(.07, .9 / g.n)
    css = ('.rise{transform-box:fill-box;transform-origin:50% 100%;animation:rise .7s cubic-bezier(.2,.8,.2,1) both;'
           f'animation-delay:{delay:.2f}s}}@keyframes rise{{from{{transform:scaleY(0);opacity:0}}}}')
    s = SVG(w, g.h, theme, candle_title(view.code, candle), css)
    cx, body, kind = w / 2, g.body, direction(candle)
    if index in date_labels(view, mobile):
        s.line(cx, g.top - 12, cx, g.vol_bottom, "grid", 1)
    for tick in g.ticks():
        s.line(0, g.y(tick), w, g.y(tick), "grid")
    s.line(0, g.vol_bottom + .5, w, g.vol_bottom + .5, "grid")
    last = candles[-1]
    s.line(0, g.y(last["close"]), w, g.y(last["close"]), tone(view.lines_change), 1.2, stroke_dasharray="4 3", opacity=".8")
    stroke = 1.6 if mobile else 1.5
    if candle["commits"]:
        top, bottom = sorted((g.y(candle["open"]), g.y(candle["close"])))
        if bottom - top < 2:
            top, bottom = top - 1, bottom + 1
        s.add('<g class="rise">')
        s.line(cx, g.y(candle["high"]), cx, g.y(candle["low"]), kind, stroke)
        if kind == "up":
            s.rect(cx - body / 2 + stroke / 2, top, body - stroke, bottom - top, "bg", 1, stroke=s.color("up"),
                   stroke_width=stroke)
        else:
            s.rect(cx - body / 2, top, body, bottom - top, "down", 1)
        s.add("</g>")
        height = candle["commits"] / g.max_commits * (g.vol_bottom - g.vol_top)
        s.rect(cx - body / 2, g.vol_bottom - height, body, max(height, 2), "up_fill" if kind == "up" else "down_fill", 1,
               opacity=".9")
    else:
        # A quiet dot for a period without commits, so real candles carry the chart.
        s.add(f'<circle cx="{cx:.1f}" cy="{g.y(candle["close"]):.1f}" r="{2 if mobile else 1.7}" '
              f'fill="{s.color("flat")}" opacity=".65"/>')
    # Moving averages: each slice draws half-segments to its neighbours, so the lines run unbroken.
    for values, color in zip(view.moving_averages, s.p["ma"]):
        value = values[index]
        if value is None:
            continue
        points = []
        if index and values[index - 1] is not None:
            points.append((0, g.y((values[index - 1] + value) / 2)))
        points.append((cx, g.y(value)))
        if index + 1 < g.n and values[index + 1] is not None:
            points.append((w, g.y((value + values[index + 1]) / 2)))
        if len(points) > 1:
            path = "M" + " L".join(f"{px:.1f} {py:.1f}" for px, py in points)
            s.add(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.3" stroke-linejoin="round" opacity=".9"/>')
    size = 14 if mobile else 11
    for target, value, offset in ((g.high_index, candle["high"], -7), (g.low_index, candle["low"], size + 5)):
        if index == target and candle["commits"] and text_width(num(value), size, 600) < w - 4:
            s.text(cx, g.y(value) + offset, num(value), size, "muted", 600, "middle")
    if candle["current"]:
        s.add(f'<circle class="pulse" cx="{cx:.1f}" cy="{g.y(candle["close"]):.1f}" r="3" '
              f'fill="{s.color(tone(view.lines_change))}"/>')
    return s


def chart_axis(view: View, theme: str, mobile: bool) -> SVG:
    candles = view.candles
    g = Geometry(candles, mobile)
    w = g.axis_w
    s = SVG(w, g.h, theme, "Price axis; the tag marks the latest close")
    size = 13 if mobile else 11
    last = candles[-1]
    color = tone(view.lines_change)
    tag_h, y = (24 if mobile else 20), g.y(last["close"])
    for tick in g.ticks():
        s.line(0, g.y(tick), w, g.y(tick), "grid")
        label_y = g.y(tick) - 4
        if not (label_y > y - tag_h / 2 - 2 and label_y - size < y + tag_h / 2 + 2):
            s.text(w - 6, label_y, compact(tick), size, "muted", 500, "end")
    s.line(0, g.vol_bottom + .5, w, g.vol_bottom + .5, "grid")
    s.rect(0, y - tag_h / 2, w - 2, tag_h, color, 3)
    s.text((w - 2) / 2, y + size * .36, compact(last["close"]), size, "#ffffff", 700, "middle")
    s.text(w - 6, g.vol_top + size, f"VOL {g.max_commits}", size, "muted", 500, "end")
    return s


def chart_dates(view: View, theme: str, mobile: bool) -> SVG:
    candles = view.candles
    g = Geometry(candles, mobile)
    size, h = (15, 30) if mobile else (11, 24)
    s = SVG(g.full_w, h, theme, "Dates")
    for i, label in date_labels(view, mobile).items():
        s.text((i + .5) * g.slice_w, h - 9, label, size, "muted", 500, "middle")
    return s


# ---------------------------------------------------------------- lists

ROW = {
    False: dict(w=846, h=80, logo=(46, 22), text_x=84, name=19, sub=13, spark=(352, 170),
                value_x=684, value=20, badge=(702, 120), badge_size=17, pad=24),
    True: dict(w=400, h=104, logo=(34, 20), text_x=64, name=19, sub=15, spark=(186, 40),
               value_x=304, value=19, badge=(312, 80), badge_size=15, pad=16),
}


def section_header(title: str, columns: tuple[str, ...], theme: str, mobile: bool) -> SVG:
    """Section title with a chevron; list sections also get a column legend: (first, second, third)."""
    L = ROW[mobile]
    w = L["w"]
    h = (84 if mobile else 70) if columns else (52 if mobile else 46)
    s = SVG(w, h, theme, title)
    size, title_y = (26, 38) if mobile else (22, 32)
    s.text(L["pad"], title_y, title, size, "fg", 700)
    s.chevron(w - L["pad"] - 8, title_y - size * .36, 8 if mobile else 7)
    if columns:
        small, y = (15 if mobile else 12), h - 12
        s.text(L["pad"], y, columns[0], small, "muted", 500)
        s.text(L["value_x"], y, columns[1], small, "muted", 500, "end")
        s.text(w - L["pad"], y, columns[2], small, "muted", 500, "end")
        s.line(L["pad"], h - .5, w - L["pad"], h - .5, "faint")
    return s


def list_row(theme: str, mobile: bool, *, logo: dict, name: str, sub: str, series: list, value: str,
             value_sub: str, change: float, change_label: str, label: str, value_sub_tone: str = "muted",
             badge_fill: str | None = None) -> SVG:
    L = ROW[mobile]
    w, h = L["w"], L["h"]
    s = SVG(w, h, theme, label)
    lx, r = L["logo"]
    sx, sw = L["spark"]
    if "wordmark" in logo:
        # A wordmark is the name itself, so it takes the place of the disc and the title.
        mark_h = 26 if mobile else 24
        s.image(logo["wordmark"][theme], lx - r, h / 2 - mark_h - 2, sx - (lx - r) - 18, mark_h, "xMinYMid meet")
        s.text(lx - r, h / 2 + L["sub"] + 6, fit(sub, L["sub"], sx - lx), L["sub"], "muted", 400)
    else:
        s.logo(lx, h / 2, r, logo)
        room = sx - L["text_x"] - 14
        s.text(L["text_x"], h / 2 - 4, fit(name, L["name"], room, 500), L["name"], "fg", 500)
        s.text(L["text_x"], h / 2 + L["sub"] + 6, fit(sub, L["sub"], room), L["sub"], "muted", 400)
    s.sparkline(series, sx, h / 2 - 22, sw, 40, tone(change) if change else "up", dot=False)
    value_room = L["badge"][0] - (sx + sw) - 14
    s.text(L["value_x"], h / 2 - 2, fit(value, L["value"], value_room, 600), L["value"], "fg", 600, "end")
    s.text(L["value_x"], h / 2 + L["sub"] + 6, fit(value_sub, L["sub"] - 1, value_room), L["sub"] - 1, value_sub_tone,
           500 if value_sub_tone != "muted" else 400, "end")
    bx, bw = L["badge"]
    bh = 40 if mobile else 38
    s.badge(bx, h / 2 - bh / 2, bw, bh, change, change_label, L["badge_size"], badge_fill)
    s.line(L["pad"], h - .5, w - L["pad"], h - .5, "grid")
    return s


def project_row(view: View, i: int, theme: str, mobile: bool) -> SVG:
    project = view.market.config["projects"][i]
    events = view.market.events("repo-lines", project["repository"])
    commits = sum(1 for row in view.market.commits if row["repository"].lower() == project["repository"].lower())
    change, badge, fill = view.badge(events)
    logo = {"file": project["logo"], "scale": .7, "fit": project.get("logo_fit", "cover")}
    sub = project["ticker"] if mobile else f"{project['ticker']} · {commits:,} commits"
    return list_row(theme, mobile, logo=logo, name=project["name"], sub=sub,
                    series=view.series(events), value=num(sum(events.values())), value_sub=signed(change),
                    value_sub_tone=tone(change), change=change, change_label=badge, badge_fill=fill,
                    label=f"{project['name']} repository")


def language_row(view: View, i: int, theme: str, mobile: bool) -> SVG:
    market = view.market
    language, size = market.languages[i]
    events = market.events("language", language)
    recent, net, share = view.change(events), sum(events.values()), size / market.language_total * 100
    return list_row(theme, mobile, logo=market.logo(language), name=language, sub=size_label(size),
                    series=view.series(events), value="<0.1%" if share < .1 else f"{share:.1f}%",
                    value_sub=signed(net, True) if mobile else f"{signed(net, True)} lines", change=recent,
                    change_label=signed(recent, True), label=language)


def collaboration_row(view: View, i: int, theme: str, mobile: bool) -> SVG:
    market = view.market
    entry = market.config["collaborations"][i]
    repository = entry["repository"]
    source = next((row for row in market.open_source["repositories"] if row["name"].lower() == repository.lower()), {})
    events = market.events("prs", repository)
    change, badge, fill = view.badge(events)
    logo = {"wordmark": entry["wordmark"]} if "wordmark" in entry else {"file": entry["logo"], "fit": "cover"}
    stars = f"★ {kilo(market.stars_of(repository))}"
    sub = stars if mobile and "wordmark" not in entry else f"{source.get('language') or 'Open source'} · {stars}"
    return list_row(theme, mobile, logo=logo, name=entry["name"], sub=sub, series=view.series(events),
                    value=f"{int(sum(events.values())):,}", value_sub=signed(change), value_sub_tone=tone(change),
                    change=change, change_label=badge, badge_fill=fill, label=f"{entry['name']} merged pull requests")


def stack_tile(view: View, tool: str, theme: str, mobile: bool) -> SVG:
    market = view.market
    repos = market.data.get("stack", {}).get(tool, [])
    events = market.stack_events(tool)
    commits, recent = int(sum(events.values())), view.change(events)
    color = tone(recent) if recent else "up"
    w, h = (200, 168) if mobile else (421, 104)
    s = SVG(w, h, theme, tool)
    s.rect(4, 4, w - 8, h - 8, "card", 16 if mobile else 14)
    repo_text = f"{len(repos)} repo{'s' if len(repos) != 1 else ''}"
    spec = market.logo(tool)
    if mobile:
        s.logo(36, 38, 18, spec)
        s.text(62, 44, fit(tool, 17, w - 76, 600), 17, "fg", 600)
        s.text(20, 92, f"{commits:,}", 28, "fg", 700)
        s.text(20, 116, f"commits · {repo_text}", 14, "muted", 500)
        s.sparkline(view.series(events), 20, 126, w - 40, 26, color, dot=False)
    else:
        s.logo(46, h / 2, 22, spec)
        s.text(80, h / 2 - 4, fit(tool, 18, 132, 600), 18, "fg", 600)
        s.text(80, h / 2 + 18, repo_text, 13, "muted", 500)
        s.sparkline(view.series(events), 222, h / 2 - 20, 92, 40, color, dot=False)
        s.text(w - 22, h / 2 - 2, f"{commits:,}", 20, "fg", 700, "end")
        s.text(w - 22, h / 2 + 18, f"{signed(recent)} {view.label}", 13, color if recent else "muted", 600, "end")
    return s


def achievement_tile(achievement: dict, theme: str, mobile: bool) -> SVG:
    w, h = (200, 206) if mobile else (421, 112)
    s = SVG(w, h, theme, f"{achievement['rank']}, {achievement['event']}")
    s.rect(4, 4, w - 8, h - 8, "card", 16 if mobile else 14)
    box = 48 if mobile else 60
    bx, by = (18, 18) if mobile else (20, (h - 60) / 2)
    filename = achievement["logo"]
    s.logo(bx + box / 2, by + box / 2, box / 2, {"file": filename, "scale": .78 if filename.endswith(".png") else .62},
           square=True)
    tag_size, tag_h = (14, 26) if mobile else (12, 22)
    tag_w = text_width(achievement["tag"], tag_size, 600) + 18
    if tag_w < w - (bx + box) - 30:
        tx = w - 16 - tag_w
        s.rect(tx, 18, tag_w, tag_h, "bg", tag_h / 2)
        s.text(tx + tag_w / 2, 18 + tag_h / 2 + tag_size * .36, achievement["tag"], tag_size, "muted", 600, "middle")
    if mobile:
        y = 96
        for line in wrap(achievement["rank"], 20, w - 36, 700)[:2]:
            s.text(18, y, line, 20, "fg", 700)
            y += 24
        for line in wrap(achievement["event"], 14, w - 36)[:3]:
            s.text(18, y + 2, line, 14, "muted", 500)
            y += 19
    else:
        x = bx + box + 18
        s.text(x, h / 2 - 2, fit(achievement["rank"], 21, w - x - 20, 700), 21, "fg", 700)
        s.text(x, h / 2 + 22, fit(achievement["event"], 14, w - x - 20, 500), 14, "muted", 500)
    return s


# ---------------------------------------------------------------- pages

class Page:
    def __init__(self, base: str):
        self.base = base

    def picture(self, name: str, alt: str, width: str, title: str | None = None) -> str:
        url = f"{self.base}assets/gen/{name}"
        hover = f' title="{escape(title)}"' if title else ""
        return (f'<picture><source media="(prefers-color-scheme: dark) and (max-width: 600px)" srcset="{url}-dark-m.svg">'
                f'<source media="(max-width: 600px)" srcset="{url}-light-m.svg">'
                f'<source media="(prefers-color-scheme: dark)" srcset="{url}-dark.svg">'
                f'<img src="{url}-light.svg" width="{width}" alt="{escape(alt)}"{hover}></picture>')

    @staticmethod
    def link(href: str | None, inner: str, title: str | None = None) -> str:
        if not href:
            return inner
        hover = f' title="{escape(title)}"' if title else ""
        return f'<a href="{escape(href)}"{hover}>{inner}</a>'


def commit_search(username: str, first: date, last: date) -> str:
    """GitHub commit search for a date range in my own public repositories (profile repo excluded)."""
    query = f"author:{username} user:{username} -repo:{username}/{username} committer-date:{first}..{last}"
    return "https://github.com/search?type=commits&q=" + query.replace(":", "%3A").replace(" ", "+").replace("/", "%2F")


def tab_url(code: str) -> str:
    return PROFILE_URL if code == DEFAULT_VIEW else VIEW_URL.format(code)


def render_page(view: View, base: str, banner: str) -> str:
    market, config = view.market, view.market.config
    r = Page(base)
    username, portfolio, p = market.username, config["portfolio"], view.prefix
    rows = lambda items: "<br>".join(r.link(href, r.picture(name, label, "100%", label), label) for name, label, href in items)
    pairs = lambda cells: "<br>".join("".join(cells[i:i + 2]) for i in range(0, len(cells), 2))
    tabs = "".join(r.link(tab_url(code), r.picture(f"tab-{code.lower()}-{'on' if code == view.code else 'off'}",
                                                     f"{name} view", f"{TAB_PCT}%", f"{name} view"), f"{name} view")
                   for code, (name, _, _) in VIEWS.items())
    tiles = "".join(r.link(href, r.picture(f"{p}-index-{key}", f"{title} index", "33.2%", tip), tip)
                    for (key, title, _), href, tip in zip(INDEX_TILES, (
                        f"https://github.com/{username}?tab=repositories&sort=stargazers",
                        commit_search(username, market.first, market.today),
                        market.open_source["url"]), (
                        "Stars on my repositories plus the projects that merged my pull requests",
                        "Every commit I have authored in my public repositories",
                        "Pull requests merged into other people's projects")))
    g = Geometry(view.candles, False)
    slices = "".join(r.link(commit_search(username, candle["start"], min(candle["end"], market.today)),
                            r.picture(f"{p}-chart-{i:02d}", candle_title(view.code, candle), f"{g.slice_pct}%",
                                      candle_title(view.code, candle)), candle_title(view.code, candle))
                     for i, candle in enumerate(view.candles))
    projects = [(f"{p}-project-{i}", f"{project['name']} on GitHub", f"https://github.com/{project['repository']}")
                for i, project in enumerate(config["projects"])]
    languages = [(f"{p}-lang-{i}", language,
                  f"https://github.com/search?q=user%3A{username}+language%3A{language.replace(' ', '+')}&type=repositories")
                 for i, (language, _) in enumerate(market.languages)]
    collabs = [(f"{p}-collab-{i}", f"My merged pull requests in {entry['name']}",
                f"https://github.com/{entry['repository']}/pulls?q=is%3Apr+is%3Amerged+author%3A{username}")
               for i, entry in enumerate(config["collaborations"])]
    stack = [r.link(f"https://github.com/{username}?tab=repositories", r.picture(f"{p}-stack-{i}", tool, "49.8%", tool), tool)
             for i, tool in enumerate(market.tools)]
    record = [r.link(a["url"], r.picture(f"record-{i}", f"{a['rank']}: {a['event']}", "49.8%", f"{a['rank']}, {a['event']}"))
              for i, a in enumerate(config["achievements"])]
    more = lambda count, noun, body: f"<details><summary>All {count} {noun}</summary>\n\n<p>{body}</p>\n\n</details>"
    banner_img = f'<img src="{banner}" width="100%" alt="The New York Stock Exchange facade at dusk">'
    return "\n\n".join(filter(None, [
        "<!-- Generated by scripts/render_profile.py. Edit profile.json or the script, not this file. -->",
        f'<p>{r.link(portfolio, banner_img, "Portfolio")}<br>{r.picture(f"{p}-tape", "Live tape", "100%")}</p>',
        f'<p>{tabs}{r.picture(f"{p}-status", f"{view.name} view", f"{STATUS_PCT}%")}</p>',
        f"<p>{tiles}</p>",
        f'<p>{r.picture(f"{p}-lines-header", "Lines index", "100%")}<br>{slices}'
        f'{r.picture(f"{p}-chart-axis", "Price axis", f"{AXIS_PCT}%")}<br>{r.picture(f"{p}-chart-dates", "Dates", "100%")}</p>',
        f'<p>{r.link(f"https://github.com/{username}?tab=repositories", r.picture(f"{p}-section-watchlist", "Watchlist", "100%"), "All repositories")}'
        f"<br>{rows(projects)}</p>",
        f'<p>{r.picture(f"{p}-section-languages", "Languages", "100%")}<br>{rows(languages[:VISIBLE_LANGUAGES])}</p>',
        more(len(languages), "languages", rows(languages[VISIBLE_LANGUAGES:])) if len(languages) > VISIBLE_LANGUAGES else "",
        f'<p>{r.picture(f"{p}-section-stack", "Tech stack", "100%")}<br>{pairs(stack[:VISIBLE_TOOLS])}</p>',
        more(len(stack), "tools", pairs(stack[VISIBLE_TOOLS:])) if len(stack) > VISIBLE_TOOLS else "",
        f'<p>{r.link(market.open_source["url"], r.picture(f"{p}-section-collabs", "Collaborations", "100%"), "Every merged pull request")}'
        f"<br>{rows(collabs)}</p>",
        f'<p>{r.link(portfolio, r.picture("section-record", "Track record", "100%"), "Portfolio")}<br>{pairs(record)}</p>',
        '<p align="right"><sub>Live public data, refreshed every 15 minutes</sub></p>',
    ])) + "\n"


def build(data: dict, config: dict, base: str) -> tuple[dict[str, str], str, dict[str, str], list[str]]:
    market = Market(data, config)
    files: dict[str, str] = {}

    def emit(name, render):
        for theme in THEMES:
            for mobile in (False, True):
                files[f"{name}-{theme}{'-m' if mobile else ''}.svg"] = render(theme, mobile).svg()

    for code in VIEWS:
        for active in (True, False):
            emit(f"tab-{code.lower()}-{'on' if active else 'off'}", lambda t, m, code=code, active=active: tab(code, active, t, m))
    emit("section-record", lambda t, m: section_header("Track record", (), t, m))
    for i, achievement in enumerate(config["achievements"]):
        emit(f"record-{i}", lambda t, m, a=achievement: achievement_tile(a, t, m))
    pages: dict[str, str] = {}
    for code in VIEWS:
        view, p = View(market, code), code.lower()
        emit(f"{p}-tape", lambda t, m, v=view: tape(v, t, m))
        emit(f"{p}-status", lambda t, m, v=view: market_status(v, t, m))
        for key, *_ in INDEX_TILES:
            emit(f"{p}-index-{key}", lambda t, m, v=view, key=key: index_tile(v, key, t, m))
        emit(f"{p}-lines-header", lambda t, m, v=view: lines_header(v, t, m))
        emit(f"{p}-chart-axis", lambda t, m, v=view: chart_axis(v, t, m))
        emit(f"{p}-chart-dates", lambda t, m, v=view: chart_dates(v, t, m))
        for i in range(len(view.candles)):
            emit(f"{p}-chart-{i:02d}", lambda t, m, v=view, i=i: chart_slice(v, i, t, m))
        label = view.label
        for key, title, columns in (("watchlist", "Watchlist", ("Project", "Net lines", f"{label} %")),
                                    ("languages", "Languages", ("Language", "Share", f"{label} lines")),
                                    ("stack", "Tech stack", ()),
                                    ("collabs", "Collaborations", ("Repository", "Merged PRs", f"{label} %"))):
            emit(f"{p}-section-{key}", lambda t, m, title=title, columns=columns: section_header(title, columns, t, m))
        for i in range(len(config["projects"])):
            emit(f"{p}-project-{i}", lambda t, m, v=view, i=i: project_row(v, i, t, m))
        for i in range(len(market.languages)):
            emit(f"{p}-lang-{i}", lambda t, m, v=view, i=i: language_row(v, i, t, m))
        for i, tool in enumerate(market.tools):
            emit(f"{p}-stack-{i}", lambda t, m, v=view, tool=tool: stack_tile(v, tool, t, m))
        for i in range(len(config["collaborations"])):
            emit(f"{p}-collab-{i}", lambda t, m, v=view, i=i: collaboration_row(v, i, t, m))
        pages[code] = render_page(view, base, "assets/nyse-banner.png" if code == DEFAULT_VIEW else BANNER_LIVE)
    readme = pages.pop(DEFAULT_VIEW)
    return files, readme, pages, market.missing_logos()


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
