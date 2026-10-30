"""Render the brokerage-app profile: live SVG widgets and README.md.

Every number comes from data/activity.json; profile.json supplies names, links,
logos and the curated achievements. Each widget is written in light/dark and
desktop/phone variants that GitHub picks between with <picture> media queries.

The widgets are published to the `market` branch on every refresh, so the images
stay live without touching main. README.md only changes when its structure or a
closed candle's hover text changes, which keeps main's history quiet.
"""
from __future__ import annotations

import argparse
import base64
from datetime import date, timedelta
from html import escape
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
LOGOS = ROOT / "assets/logos"
LIVE_BASE = "https://raw.githubusercontent.com/Haoming9527/Haoming9527/market/"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"
THEMES = {
    "light": dict(bg="#ffffff", card="#f6f8fa", fg="#1f2328", muted="#59636e", faint="#d8dee4",
                  grid="#eaeef2", up="#1a7f37", up_fill="#2da44e", down="#cf222e", down_fill="#e5484d",
                  flat="#8c959f", ring="#d0d7de", pill="#eaeef2"),
    "dark": dict(bg="#0d1117", card="#151b23", fg="#f0f6fc", muted="#9198a1", faint="#2a313c",
                 grid="#1f2630", up="#3fb950", up_fill="#2ea043", down="#f85149", down_fill="#da3633",
                 flat="#6e7681", ring="#0d1117", pill="#212830"),
}
# Logo file and how much of the circle it fills.
LANGUAGE_LOGOS = {
    "JavaScript": ("javascript.svg", .56), "TypeScript": ("typescript.svg", .56), "HTML": ("html.svg", .6),
    "CSS": ("css.svg", .6), "Java": ("java.svg", .62), "Go": ("go.svg", .7), "PLpgSQL": ("postgresql.svg", .6),
    "Shell": ("shell.svg", .6), "Batchfile": ("batchfile.svg", .5), "Rust": ("rust.svg", .62),
    "Dockerfile": ("docker.svg", .64), "PowerShell": ("powershell.svg", .6),
}
STACK_LOGOS = {
    "React": ("react.svg", .64), "Next.js": ("nextjs.svg", .6), "Node.js": ("nodejs.svg", .6),
    "PostgreSQL": ("postgresql.svg", .6), "Docker": ("docker.svg", .64), "Ollama": ("ollama.svg", .56),
    "AI SDK": ("aisdk.svg", .5), "MCP": ("mcp.svg", .56),
}
TIMEFRAMES = (("D", "1D", "Daily", "today"), ("W", "1W", "Weekly", "this week"), ("M", "1M", "Monthly", "this month"),
              ("Q", "1Q", "Quarterly", "this quarter"), ("Y", "1Y", "Yearly", "this year"))
DEFAULT_TIMEFRAME = "W"
MINUS = "\u2212"
VISIBLE_LANGUAGES = 6
RECENT = 30  # days behind every row badge


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


def day(value: str) -> date:
    return date.fromisoformat(value[:10])


def tone(value: float) -> str:
    return "up" if value > 0 else "down" if value < 0 else "flat"


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

    def sparkline(self, values, x, y, w, h, stroke, fill=True, dot=True, width=2):
        values = list(values) or [0]
        if len(values) == 1:
            values *= 2
        lo, hi = min(values), max(values)
        span = hi - lo
        points = [(x + i / (len(values) - 1) * w, y + h / 2 if not span else y + h - (v - lo) / span * h)
                  for i, v in enumerate(values)]
        path = "M" + " L".join(f"{px:.1f} {py:.1f}" for px, py in points)
        color = self.color(stroke)
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

    def logo(self, cx, cy, r, filename: str, scale: float = .6, fit_mode: str = "contain"):
        """A real logo in a white disc, the way brokerage apps show tickers."""
        clip = self.next_id()
        self.add(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:g}" fill="#ffffff" stroke="{self.color("ring")}" '
                 f'stroke-width="1"/><clipPath id="{clip}"><circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r - .5:g}"/></clipPath>')
        source = LOGOS / filename
        if source.suffix == ".svg":
            markup = source.read_text(encoding="utf-8")
            view_box = re.search(r'viewBox="([^"]+)"', markup).group(1)
            inner = re.sub(r"(?s)^.*?<svg[^>]*>|</svg>\s*$|<title>.*?</title>", "", markup)
            prefix = self.next_id()
            inner = re.sub(r'id="([^"]+)"', lambda m: f'id="{prefix}{m.group(1)}"', inner)
            inner = re.sub(r"url\(#([^)]+)\)", lambda m: f"url(#{prefix}{m.group(1)})", inner)
            side = 2 * r * scale
            self.add(f'<svg x="{cx - side / 2:.1f}" y="{cy - side / 2:.1f}" width="{side:.1f}" height="{side:.1f}" '
                     f'viewBox="{view_box}">{inner}</svg>')
        else:
            mime = "image/png" if source.suffix == ".png" else "image/jpeg"
            data = base64.b64encode(source.read_bytes()).decode()
            side = 2 * r if fit_mode == "cover" else 2 * r * scale
            aspect = "xMidYMid slice" if fit_mode == "cover" else "xMidYMid meet"
            self.add(f'<image href="data:{mime};base64,{data}" x="{cx - side / 2:.1f}" y="{cy - side / 2:.1f}" '
                     f'width="{side:.1f}" height="{side:.1f}" preserveAspectRatio="{aspect}" clip-path="url(#{clip})"/>')

    def chevron(self, x, y, size=9, stroke="muted"):
        self.add(f'<path d="M{x:.1f} {y - size:.1f} L{x + size * .62:.1f} {y:.1f} L{x:.1f} {y + size:.1f}" fill="none" '
                 f'stroke="{self.color(stroke)}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>')

    def badge(self, x, y, w, h, value: float, label: str, size: float):
        fill = "up_fill" if value > 0 else "down_fill" if value < 0 else "flat"
        self.rect(x, y, w, h, fill, 6)
        self.text(x + w / 2, y + h / 2 + size * .36, fit(label, size, w - 8, 700), size, "#ffffff", 700, "middle")

    def svg(self) -> str:
        return "\n".join(self.parts + ["</svg>"]) + "\n"


# ---------------------------------------------------------------- derived data

def month_start(when: date, offset: int = 0) -> date:
    index = when.year * 12 + when.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def periods(timeframe: str, first: date, today: date) -> list[tuple[date, date]]:
    if timeframe == "D":
        return [(today - timedelta(days=29 - i),) * 2 for i in range(30)]
    if timeframe == "W":
        monday = today - timedelta(days=today.weekday())
        return [(monday - timedelta(weeks=25 - i), monday - timedelta(weeks=25 - i) + timedelta(days=6)) for i in range(26)]
    span, count = {"M": (1, 24), "Q": (3, 12), "Y": (12, 8)}[timeframe]
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


def period_label(timeframe: str, begin: date, long: bool = False) -> str:
    if timeframe == "D":
        return f"{begin:%a %d %b %Y}" if long else f"{begin:%b} {begin.day}"
    if timeframe == "W":
        return f"Week of {begin:%d %b %Y}" if long else f"{begin:%b} {begin.day}"
    if timeframe == "M":
        return f"{begin:%B %Y}" if long else (f"{begin:%b} '{begin:%y}" if begin.month == 1 else f"{begin:%b}")
    if timeframe == "Q":
        return f"Q{(begin.month - 1) // 3 + 1} {begin.year}" if long else f"Q{(begin.month - 1) // 3 + 1} '{begin:%y}"
    return str(begin.year)


class Market:
    """Daily series, candles and summaries derived from one activity snapshot."""

    def __init__(self, data: dict, config: dict):
        self.data, self.config = data, config
        self.username = data["github_username"]
        self.today = day(data["generated_at"])
        self.start = day(data["window"]["start"])
        self.days = [self.start + timedelta(days=i) for i in range((self.today - self.start).days + 1)]
        self.commits = sorted(data["commits"], key=lambda row: (row["timestamp"], row["sha"]))
        self.first = day(self.commits[0]["timestamp"]) if self.commits else self.today
        self.open_source = data["open_source"]
        self.lines = sum(row["additions"] - row["deletions"] for row in self.commits)

    # Daily cumulative series over the activity window, for the index tiles.
    def cumulative(self, events: dict[date, int], base: int = 0) -> list[int]:
        series, total = [], base
        for current in self.days:
            total += events.get(current, 0)
            series.append(total)
        return series

    def index(self, key: str) -> dict:
        if key == "stars":
            events: dict[date, int] = {}
            for repo in self.data["stars"]["repositories"]:
                for when, count in repo["starred_on"].items():
                    events[day(when)] = events.get(day(when), 0) + count
            dated = events
        elif key == "commits":
            dated = {}
            for row in self.commits:
                dated[day(row["timestamp"])] = dated.get(day(row["timestamp"]), 0) + 1
        else:
            dated = {}
            for repo in self.open_source["repositories"]:
                for stamp in repo["merged_at"]:
                    dated[day(stamp)] = dated.get(day(stamp), 0) + 1
        recent = {when: count for when, count in dated.items() if when >= self.start}
        # Stars without dates (hidden stargazer lists) count as older than the window.
        total = self.data["stars"]["total"] if key == "stars" else sum(dated.values())
        series = self.cumulative(recent, total - sum(recent.values()))
        previous = series[-8] if len(series) > 7 else series[0]
        return {"series": series, "value": series[-1], "delta": series[-1] - previous, "previous": previous}

    def candles(self, timeframe: str) -> list[dict]:
        spans = periods(timeframe, self.first, self.today)
        index = sum(row["additions"] - row["deletions"] for row in self.commits if day(row["timestamp"]) < spans[0][0])
        result = []
        for begin, end in spans:
            candle = {"start": begin, "end": end, "open": index, "high": index, "low": index, "close": index,
                      "additions": 0, "deletions": 0, "commits": 0, "current": begin <= self.today <= end}
            for row in self.commits:
                if begin <= day(row["timestamp"]) <= end:
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

    def trend(self, events: dict[date, float], points: int = 60, minimum_days: int = 30) -> list[float]:
        """Cumulative values from the first event to today, resampled for a sparkline."""
        if not events:
            return [0, 0]
        first = min(min(events), self.today - timedelta(days=minimum_days))
        span = max((self.today - first).days, 1)
        ordered = sorted(events.items())
        series, total, cursor = [], 0.0, 0
        for i in range(points + 1):
            cutoff = first + timedelta(days=span * i / points)
            while cursor < len(ordered) and ordered[cursor][0] <= cutoff:
                total += ordered[cursor][1]
                cursor += 1
            series.append(total)
        return series

    def recent(self, events: dict[date, float]) -> float:
        return sum(value for when, value in events.items() if when > self.today - timedelta(days=RECENT))

    def repo_events(self, repository: str, lines: bool = True) -> dict[date, float]:
        events: dict[date, float] = {}
        for row in self.commits:
            if row["repository"].lower() == repository.lower():
                when = day(row["timestamp"])
                events[when] = events.get(when, 0) + (row["additions"] - row["deletions"] if lines else 1)
        return events

    def language_events(self, language: str) -> dict[date, float]:
        events: dict[date, float] = {}
        for row in self.commits:
            added, deleted = row.get("languages", {}).get(language, (0, 0))
            if added or deleted:
                when = day(row["timestamp"])
                events[when] = events.get(when, 0) + added - deleted
        return events

    def stack_events(self, tool: str) -> dict[date, float]:
        repos = {name.lower() for name in self.data["stack"].get(tool, [])}
        events: dict[date, float] = {}
        for row in self.commits:
            if row["repository"].lower() in repos:
                when = day(row["timestamp"])
                events[when] = events.get(when, 0) + 1
        return events

    def stars_of(self, repository: str) -> int:
        return next((row["stars"] for row in self.data["stars"]["repositories"]
                     if row["name"].lower() == repository.lower()), 0)


# ---------------------------------------------------------------- widgets

def tape(market: Market, theme: str, mobile: bool) -> SVG:
    w, h, size = (400, 46, 17) if mobile else (846, 40, 14)
    items = [("ECON", market.config["role"], "", "none")]
    for key, label in (("stars", "STARS"), ("commits", "COMMITS"), ("prs", "MERGED PRS")):
        index = market.index(key)
        items.append((label, num(index["value"]), signed(index["delta"]), tone(index["delta"])))
    today = market.candles("D")[-1]
    change = today["close"] - today["open"]
    items.append(("LINES", num(market.lines), signed(change), tone(change)))
    sizes = market.data["languages"]["bytes"]
    total = sum(sizes.values()) or 1
    for name, size_bytes in list(sizes.items())[:4]:
        recent = market.recent(market.language_events(name))
        items.append((name.upper(), f"{size_bytes / total * 100:.1f}%", signed(recent, True), tone(recent)))
    for project in market.config["projects"]:
        events = market.repo_events(project["repository"])
        recent = market.recent(events)
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
        for px, label, value, change, direction in pieces:
            px += offset + size
            s.text(px, baseline, label, size, "muted", 600)
            px += text_width(label, size, 600) + size * .6
            s.text(px, baseline, value, size, "fg", 600)
            if direction != "none":
                px += text_width(value, size, 600) + size * .6
                arrow = "▲" if direction == "up" else "▼" if direction == "down" else "■"
                s.text(px, baseline, f"{arrow} {change}", size, direction, 600)
    s.add("</g>")
    return s


INDEX_TILES = (("stars", "Stars", "mine + collab"), ("commits", "Commits", "all time"), ("prs", "Merged PRs", "external"))


def index_tile(market: Market, key: str, theme: str, mobile: bool) -> SVG:
    title, hint = next((title, hint) for k, title, hint in INDEX_TILES if k == key)
    index = market.index(key)
    color = tone(index["delta"])
    w, h = (200, 214) if mobile else (282, 178)
    s = SVG(w, h, theme, f"{title} index")
    s.rect(4, 4, w - 8, h - 8, "card", 16 if mobile else 14)
    x = 20 if mobile else 22
    change = f"{signed(index['delta'])} {percent(index['delta'], index['previous'])}".strip()
    if mobile:
        s.text(x, 44, title, 22, "fg", 500)
        s.text(x, 90, num(index["value"]), 36, color, 700)
        s.text(x, 122, change, 19, color, 500)
        s.sparkline(index["series"], x, 140, w - 2 * x, 46, color)
    else:
        s.text(x, 38, title, 18, "fg", 500)
        s.text(w - x, 38, hint, 12, "muted", 500, "end")
        s.text(x, 78, num(index["value"]), 32, color, 700)
        s.text(x, 104, f"{change}  7D", 14, color, 500)
        s.sparkline(index["series"], x, 118, w - 2 * x, 40, color)
    return s


# ---------------------------------------------------------------- candle chart

AXIS_PCT = 14.0


class Geometry:
    def __init__(self, candles: list[dict], mobile: bool):
        self.candles, self.n, self.mobile = candles, len(candles), mobile
        self.slice_pct = round((99.6 - AXIS_PCT) / self.n, 3)
        unit = 4.0 if mobile else 8.46            # canvas units per percent of README width
        self.slice_w, self.axis_w = self.slice_pct * unit, AXIS_PCT * unit
        self.full_w = 100 * unit
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


def candle_title(timeframe: str, candle: dict) -> str:
    label = period_label(timeframe, candle["start"], True)
    if candle["current"]:
        return f"{label}, in progress (updates live)"
    if not candle["commits"]:
        return f"{label}: no commits; index {num(candle['close'])}"
    return (f"{label}: {candle['commits']} commit{'s' if candle['commits'] != 1 else ''}, "
            f"+{candle['additions']:,} / {MINUS}{candle['deletions']:,} lines; open {num(candle['open'])}, "
            f"high {num(candle['high'])}, low {num(candle['low'])}, close {num(candle['close'])}")


def chart_slice(market: Market, timeframe: str, index: int, theme: str, mobile: bool) -> SVG:
    candles = market.candles(timeframe)
    g = Geometry(candles, mobile)
    candle, w = candles[index], g.slice_w
    delay = index * min(.07, .9 / g.n)
    css = ('.rise{transform-box:fill-box;transform-origin:50% 100%;animation:rise .7s cubic-bezier(.2,.8,.2,1) both;'
           f'animation-delay:{delay:.2f}s}}@keyframes rise{{from{{transform:scaleY(0);opacity:0}}}}')
    s = SVG(w, g.h, theme, candle_title(timeframe, candle), css)
    for tick in g.ticks():
        s.line(0, g.y(tick), w, g.y(tick), "grid")
    s.line(0, g.vol_bottom + .5, w, g.vol_bottom + .5, "grid")
    last = candles[-1]
    last_tone = tone(last["close"] - last["open"]) if last["close"] != last["open"] else "flat"
    s.line(0, g.y(last["close"]), w, g.y(last["close"]), last_tone, 1.2, stroke_dasharray="4 3", opacity=".8")
    cx, body, kind = w / 2, g.body, direction(candle)
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
        s.line(cx - body / 2, g.y(candle["close"]), cx + body / 2, g.y(candle["close"]), "flat", stroke)
    size = 14 if mobile else 11
    for target, value, offset in ((g.high_index, candle["high"], -7), (g.low_index, candle["low"], size + 5)):
        if index == target and candle["commits"] and text_width(num(value), size, 600) < w - 4:
            s.text(cx, g.y(value) + offset, num(value), size, "muted", 600, "middle")
    if candle["current"]:
        s.add(f'<circle class="pulse" cx="{cx:.1f}" cy="{g.y(candle["close"]):.1f}" r="3" fill="{s.color(kind)}"/>')
    return s


def chart_axis(market: Market, timeframe: str, theme: str, mobile: bool) -> SVG:
    candles = market.candles(timeframe)
    g = Geometry(candles, mobile)
    w = g.axis_w
    s = SVG(w, g.h, theme, "Price axis; the tag marks the latest close")
    size = 13 if mobile else 11
    last = candles[-1]
    color = tone(last["close"] - last["open"]) if last["close"] != last["open"] else "flat"
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


def chart_dates(market: Market, timeframe: str, theme: str, mobile: bool) -> SVG:
    candles = market.candles(timeframe)
    g = Geometry(candles, mobile)
    size = 15 if mobile else 11
    h = 30 if mobile else 24
    s = SVG(g.full_w, h, theme, "Dates")
    labels = [period_label(timeframe, candle["start"]) for candle in candles]
    widest = max(text_width(label, size, 500) for label in labels) + (10 if mobile else 14)
    step = max(1, math.ceil(widest / g.slice_w))
    for i in range(g.n - 1, -1, -step):
        x = (i + .5) * g.slice_w
        if x - text_width(labels[i], size, 500) / 2 >= 0:
            s.text(x, h - 9, labels[i], size, "muted", 500, "middle")
    return s


def chart_header(market: Market, theme: str, mobile: bool) -> SVG:
    commits = market.commits
    additions = sum(row["additions"] for row in commits)
    deletions = sum(row["deletions"] for row in commits)
    today = market.candles("D")[-1]
    change = today["close"] - today["open"]
    w, h = (400, 128) if mobile else (846, 96)
    s = SVG(w, h, theme, "Lines index: net lines of code I have added across my public repositories")
    pad = 18 if mobile else 24
    title_size = 22 if mobile else 18
    s.text(pad, 34 if mobile else 30, "Lines index", title_size, "fg", 600)
    s.text(pad + text_width("Lines index", title_size, 600) + 10, 34 if mobile else 30,
           f"since {market.first:%b %Y}", 15 if mobile else 13, "muted", 500)
    value_size = 38 if mobile else 32
    value_y = 80 if mobile else 72
    s.text(pad, value_y, num(market.lines), value_size, "fg", 700)
    today_text = f"{signed(change)} today" if change else "flat today"
    if mobile:
        s.text(pad, 112, f"{today_text}   +{compact(additions)} / {MINUS}{compact(deletions)}   {len(commits)} commits",
               16, "muted", 500)
    else:
        s.text(pad + text_width(num(market.lines), value_size, 700) + 14, value_y, today_text, 16, tone(change), 500)
        stats = (("Commits", f"{len(commits):,}"), ("Added", f"+{compact(additions)}"), ("Deleted", f"{MINUS}{compact(deletions)}"))
        x = w - pad
        for label, value in reversed(stats):
            s.text(x, 50, value, 15, "fg", 600, "end")
            s.text(x, 72, label, 12, "muted", 500, "end")
            x -= max(text_width(value, 15, 600), text_width(label, 12, 500)) + 26
    return s


def timeframe_row(market: Market, code: str, theme: str, mobile: bool) -> SVG:
    """The clickable summary for one timeframe of the accordion."""
    _, pill, name, period = next(item for item in TIMEFRAMES if item[0] == code)
    candles = market.candles(code)
    current = candles[-1]
    change = current["close"] - current["open"]
    w, h = (376, 70) if mobile else (800, 58)
    s = SVG(w, h, theme, f"{pill} {name} candles")
    pill_w, pill_h = (56, 38) if mobile else (52, 34)
    s.rect(2, (h - pill_h) / 2, pill_w, pill_h, "pill", pill_h / 2)
    s.text(2 + pill_w / 2, h / 2 + (16 if mobile else 14) * .36, pill, 16 if mobile else 14, "fg", 700, "middle")
    x = pill_w + (14 if mobile else 18)
    s.text(x, h / 2 - (3 if mobile else 2), name, 19 if mobile else 16, "fg", 600)
    s.text(x, h / 2 + (19 if mobile else 16), f"{len(candles)} candles", 14 if mobile else 12, "muted", 500)
    spark_x, spark_w = (178, 92) if mobile else (330, 220)
    s.sparkline([candle["close"] for candle in candles], spark_x, h / 2 - 16, spark_w, 32, tone(change) if change else "up",
                fill=False, dot=False, width=1.8)
    badge_w, badge_h = (88, 38) if mobile else (104, 34)
    if not mobile:
        s.text(w - badge_w - 14, h / 2 + 5, period, 13, "muted", 500, "end")
    s.badge(w - badge_w - 2, (h - badge_h) / 2, badge_w, badge_h, change, signed(change, True), 16 if mobile else 15)
    return s


# ---------------------------------------------------------------- lists

ROW = {
    False: dict(w=846, h=80, logo=(46, 22), text_x=84, name=19, sub=13, spark=(352, 170),
                value_x=684, value=20, badge=(702, 120), badge_size=17, pad=24),
    True: dict(w=400, h=104, logo=(34, 20), text_x=64, name=19, sub=15, spark=(190, 44),
               value_x=316, value=20, badge=(326, 66), badge_size=16, pad=16),
}


def section_header(title: str, columns: tuple[str, ...], theme: str, mobile: bool) -> SVG:
    """Section title with a chevron; list sections also get a column legend: (first, second, third)."""
    L = ROW[mobile]
    w = L["w"]
    h = (88 if mobile else 74) if columns else (54 if mobile else 48)
    s = SVG(w, h, theme, title)
    size = 28 if mobile else 24
    s.text(L["pad"], 40 if mobile else 34, title, size, "fg", 700)
    s.chevron(w - L["pad"] - 8, (40 if mobile else 34) - size * .36, 8 if mobile else 7)
    if columns:
        small, y = (15 if mobile else 12), h - 12
        s.text(L["pad"], y, columns[0], small, "muted", 500)
        s.text(L["value_x"], y, columns[1], small, "muted", 500, "end")
        s.text(w - L["pad"], y, columns[2], small, "muted", 500, "end")
        s.line(L["pad"], h - .5, w - L["pad"], h - .5, "faint")
    return s


def list_row(theme: str, mobile: bool, *, logo: tuple, name: str, sub: str, series: list, value: str,
             value_sub: str, change: float, change_label: str, label: str) -> SVG:
    L = ROW[mobile]
    w, h = L["w"], L["h"]
    s = SVG(w, h, theme, label)
    lx, r = L["logo"]
    filename, scale, fit_mode = logo
    s.logo(lx, h / 2, r, filename, scale, fit_mode)
    room = L["spark"][0] - L["text_x"] - 14
    s.text(L["text_x"], h / 2 - 4, fit(name, L["name"], room, 500), L["name"], "fg", 500)
    s.text(L["text_x"], h / 2 + L["sub"] + 6, fit(sub, L["sub"], room), L["sub"], "muted", 400)
    sx, sw = L["spark"]
    s.sparkline(series, sx, h / 2 - 22, sw, 40, tone(change) if change else "up", dot=False)
    value_room = L["badge"][0] - (sx + sw) - 14
    s.text(L["value_x"], h / 2 - 2, fit(value, L["value"], value_room, 600), L["value"], "fg", 600, "end")
    s.text(L["value_x"], h / 2 + L["sub"] + 6, fit(value_sub, L["sub"] - 1, value_room), L["sub"] - 1, "muted", 400, "end")
    bx, bw = L["badge"]
    bh = 40 if mobile else 38
    s.badge(bx, h / 2 - bh / 2, bw, bh, change, change_label, L["badge_size"])
    s.line(L["pad"], h - .5, w - L["pad"], h - .5, "grid")
    return s


def project_rows(market: Market) -> list[tuple[str, callable, str, str]]:
    rows = []
    for i, project in enumerate(market.config["projects"]):
        repository = project["repository"]
        lines = market.repo_events(repository)
        commits = sum(market.repo_events(repository, lines=False).values())
        recent = market.recent(lines)
        logo = (project["logo"], .7, project.get("logo_fit", "cover"))

        def render(theme, mobile, project=project, lines=lines, commits=commits, recent=recent, logo=logo):
            return list_row(theme, mobile, logo=logo, name=project["name"], sub=project["ticker"],
                            series=market.trend(lines), value=num(sum(lines.values())),
                            value_sub=f"{commits:,} commits", change=recent, change_label=signed(recent, True),
                            label=f"{project['name']} repository")
        rows.append((f"project-{i}", render, f"{project['name']} on GitHub", f"https://github.com/{repository}"))
    return rows


def language_rows(market: Market) -> list[tuple[str, callable, str, str]]:
    rows = []
    sizes = market.data["languages"]["bytes"]
    total = sum(sizes.values()) or 1
    for i, (language, size) in enumerate(sizes.items()):
        events = market.language_events(language)
        recent = market.recent(events)
        filename, scale = LANGUAGE_LOGOS.get(language, ("shell.svg", .6))
        share = size / total * 100

        def render(theme, mobile, language=language, size=size, events=events, recent=recent,
                   logo=(filename, scale, "contain"), share=share):
            net = sum(events.values())
            return list_row(theme, mobile, logo=logo, name=language, sub=size_label(size),
                            series=market.trend(events), value="<0.1%" if share < .1 else f"{share:.1f}%",
                            value_sub=signed(net, True) if mobile else f"{signed(net, True)} lines", change=recent,
                            change_label=signed(recent, True),
                            label=language)
        rows.append((f"lang-{i}", render, language,
                     f"https://github.com/search?q=user%3A{market.username}+language%3A{language}&type=repositories"))
    return rows


def collaboration_rows(market: Market) -> list[tuple[str, callable, str, str]]:
    rows = []
    for i, entry in enumerate(market.config["collaborations"]):
        repository = entry["repository"]
        source = next((row for row in market.open_source["repositories"] if row["name"].lower() == repository.lower()), {})
        events: dict[date, float] = {}
        for stamp in source.get("merged_at", []):
            events[day(stamp)] = events.get(day(stamp), 0) + 1
        recent = market.recent(events)
        stars = market.stars_of(repository)

        def render(theme, mobile, entry=entry, events=events, recent=recent, stars=stars, source=source):
            return list_row(theme, mobile, logo=(entry["logo"], .7, "cover"), name=entry["name"],
                            sub=source.get("language") or "Open source", series=market.trend(events),
                            value=f"{int(sum(events.values())):,}", value_sub=f"★ {kilo(stars)}", change=recent,
                            change_label=signed(recent), label=f"{entry['name']} merged pull requests")
        link = f"https://github.com/{repository}/pulls?q=is%3Apr+is%3Amerged+author%3A{market.username}"
        rows.append((f"collab-{i}", render, f"My merged pull requests in {entry['name']}", link))
    return rows


def stack_tile(market: Market, tool: str, theme: str, mobile: bool) -> SVG:
    filename, scale = STACK_LOGOS[tool]
    repos = market.data["stack"].get(tool, [])
    events = market.stack_events(tool)
    commits, recent = int(sum(events.values())), market.recent(events)
    color = tone(recent) if recent else "up"
    w, h = (200, 168) if mobile else (421, 104)
    s = SVG(w, h, theme, f"{tool}")
    s.rect(4, 4, w - 8, h - 8, "card", 16 if mobile else 14)
    repo_text = f"{len(repos)} repo{'s' if len(repos) != 1 else ''}"
    if mobile:
        s.logo(36, 38, 18, filename, scale)
        s.text(62, 44, fit(tool, 17, w - 76, 600), 17, "fg", 600)
        s.text(20, 92, f"{commits:,}", 28, "fg", 700)
        s.text(20, 116, f"commits · {repo_text}", 14, "muted", 500)
        s.sparkline(market.trend(events), 20, 126, w - 40, 26, color, dot=False)
    else:
        s.logo(46, h / 2, 22, filename, scale)
        s.text(80, h / 2 - 4, tool, 18, "fg", 600)
        s.text(80, h / 2 + 18, repo_text, 13, "muted", 500)
        s.sparkline(market.trend(events), 196, h / 2 - 20, 110, 40, color, dot=False)
        s.text(w - 22, h / 2 - 2, f"{commits:,}", 20, "fg", 700, "end")
        s.text(w - 22, h / 2 + 18, f"{signed(recent)} 30D", 13, color if recent else "muted", 600, "end")
    return s


MEDAL = ("M10 2 L14 9 M22 2 L18 9 M16 30 A9 9 0 1 0 16 12 A9 9 0 1 0 16 30 Z M16 16 L17.6 19.4 L21.2 19.8 "
         "L18.5 22.2 L19.3 25.8 L16 24 L12.7 25.8 L13.5 22.2 L10.8 19.8 L14.4 19.4 Z")
TROPHY = "M9 4 H23 V11 A7 7 0 0 1 9 11 Z M9 6 H4 V8 A5 5 0 0 0 9.5 13 M23 6 H28 V8 A5 5 0 0 1 22.5 13 M16 18 V24 M10 28 H22 M12 24 H20 V28"
MEDAL_COLORS = {"light": ("#bf8700", "#8250df", "#0969da", "#1a7f37"), "dark": ("#e3b341", "#a371f7", "#4493f8", "#3fb950")}


def achievement_tile(achievement: dict, i: int, theme: str, mobile: bool) -> SVG:
    w, h = (200, 168) if mobile else (421, 112)
    s = SVG(w, h, theme, f"{achievement['rank']}, {achievement['event']}")
    s.rect(4, 4, w - 8, h - 8, "card", 16 if mobile else 14)
    color = MEDAL_COLORS[theme][i % 4]
    box = 44 if mobile else 52
    bx, by = (18, 18) if mobile else (22, (h - 52) / 2)
    s.rect(bx, by, box, box, "bg", 12, stroke=color, stroke_width="1.6")
    s.add(f'<path d="{TROPHY if i == 0 else MEDAL}" transform="translate({bx + box * .14:.1f} {by + box * .14:.1f}) '
          f'scale({box * .72 / 32:.3f})" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" '
          'stroke-linejoin="round"/>')
    tag_size, tag_h = (15, 26) if mobile else (12, 22)
    tag_w = text_width(achievement["tag"], tag_size, 600) + 18
    tx = w - 18 - tag_w
    s.rect(tx, 18, tag_w, tag_h, "bg", tag_h / 2)
    s.text(tx + tag_w / 2, 18 + tag_h / 2 + tag_size * .36, achievement["tag"], tag_size, "muted", 600, "middle")
    if mobile:
        s.text(18, 98, fit(achievement["rank"], 22, w - 36, 700), 22, "fg", 700)
        for j, line in enumerate(wrap(achievement["event"], 15, w - 36)[:2]):
            s.text(18, 124 + j * 20, line, 15, "muted", 500)
    else:
        x = bx + box + 18
        s.text(x, h / 2 - 2, achievement["rank"], 22, "fg", 700)
        s.text(x, h / 2 + 22, fit(achievement["event"], 14, w - x - 22, 500), 14, "muted", 500)
    return s


# ---------------------------------------------------------------- README

class Readme:
    def __init__(self, base: str):
        self.base = base

    def picture(self, name: str, alt: str, width: str, title: str | None = None, align: str | None = None) -> str:
        url = f"{self.base}assets/gen/{name}"
        hover = (f' title="{escape(title)}"' if title else "") + (f' align="{align}"' if align else "")
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


def build(data: dict, config: dict, base: str) -> tuple[dict[str, str], str]:
    market = Market(data, config)
    files: dict[str, str] = {}

    def emit(name, render):
        for theme in THEMES:
            for mobile in (False, True):
                files[f"{name}-{theme}{'-m' if mobile else ''}.svg"] = render(theme, mobile).svg()

    emit("tape", lambda t, m: tape(market, t, m))
    for key, *_ in INDEX_TILES:
        emit(f"index-{key}", lambda t, m, key=key: index_tile(market, key, t, m))
    emit("lines-header", lambda t, m: chart_header(market, t, m))
    for code, *_ in TIMEFRAMES:
        emit(f"tf-{code.lower()}", lambda t, m, code=code: timeframe_row(market, code, t, m))
        emit(f"chart-{code.lower()}-axis", lambda t, m, code=code: chart_axis(market, code, t, m))
        emit(f"chart-{code.lower()}-dates", lambda t, m, code=code: chart_dates(market, code, t, m))
        for i in range(len(market.candles(code))):
            emit(f"chart-{code.lower()}-{i:02d}", lambda t, m, code=code, i=i: chart_slice(market, code, i, t, m))
    sections = {
        "watchlist": ("Watchlist", ("Project", "Net lines", f"{RECENT}D")),
        "languages": ("Languages", ("Language", "Share", f"{RECENT}D")),
        "stack": ("Tech stack", ()),
        "collabs": ("Collaborations", ("Repository", "Merged PRs", f"{RECENT}D")),
        "record": ("Track record", ()),
    }
    for key, (title, columns) in sections.items():
        emit(f"section-{key}", lambda t, m, title=title, columns=columns: section_header(title, columns, t, m))
    projects, languages, collabs = project_rows(market), language_rows(market), collaboration_rows(market)
    for name, render, *_ in projects + languages + collabs:
        emit(name, render)
    for i, tool in enumerate(config["stack"]):
        emit(f"stack-{i}", lambda t, m, tool=tool: stack_tile(market, tool, t, m))
    for i, achievement in enumerate(config["achievements"]):
        emit(f"record-{i}", lambda t, m, a=achievement, i=i: achievement_tile(a, i, t, m))

    r = Readme(base)
    username, portfolio = market.username, config["portfolio"]
    rows = lambda items: "<br>".join(r.link(href, r.picture(name, label, "100%", label), label) for name, _, label, href in items)
    pairs = lambda cells: "<br>".join("".join(cells[i:i + 2]) for i in range(0, len(cells), 2))
    tiles = "".join(r.link(href, r.picture(f"index-{key}", f"{title} index", "33.2%", tip), tip)
                    for (key, title, _), href, tip in zip(INDEX_TILES, (
                        f"https://github.com/{username}?tab=repositories&sort=stargazers",
                        commit_search(username, market.first, market.today),
                        data["open_source"]["url"]), (
                        "Stars on my repositories plus the projects that merged my pull requests",
                        "Every commit I have authored in my public repositories",
                        "Pull requests merged into other people's projects")))
    timeframes = []
    for code, pill, name, _ in TIMEFRAMES:
        candles = market.candles(code)
        g = Geometry(candles, False)
        slices = "".join(r.link(commit_search(username, candle["start"], min(candle["end"], market.today)),
                                r.picture(f"chart-{code.lower()}-{i:02d}", candle_title(code, candle), f"{g.slice_pct}%",
                                          candle_title(code, candle)), candle_title(code, candle))
                         for i, candle in enumerate(candles))
        axis = r.picture(f"chart-{code.lower()}-axis", "Price axis", f"{AXIS_PCT}%")
        dates = r.picture(f"chart-{code.lower()}-dates", "Dates", "100%")
        summary = r.picture(f"tf-{code.lower()}", f"{pill} {name}", "94%", f"Show {name.lower()} candles", "middle")
        timeframes.append(f'<details name="timeframe"{" open" if code == DEFAULT_TIMEFRAME else ""}>'
                          f"<summary>{summary}</summary>\n\n<p>{slices}{axis}<br>{dates}</p>\n\n</details>")
    stack = [r.link(f"https://github.com/{username}?tab=repositories", r.picture(f"stack-{i}", tool, "49.8%", tool), tool)
             for i, tool in enumerate(config["stack"])]
    record = [r.link(a["url"], r.picture(f"record-{i}", f"{a['rank']}: {a['event']}", "49.8%", f"{a['rank']}, {a['event']}"))
              for i, a in enumerate(config["achievements"])]
    hidden = languages[VISIBLE_LANGUAGES:]
    banner = '<img src="assets/nyse-banner.png" width="100%" alt="The New York Stock Exchange facade at dusk">'
    readme = "\n\n".join(filter(None, [
        "<!-- Generated by scripts/render_profile.py. Edit profile.json or the script, not this file. -->",
        f'<p>{r.link(portfolio, banner, "Portfolio")}<br>{r.picture("tape", "Live tape", "100%")}</p>',
        f"<p>{tiles}</p>",
        f'<p>{r.picture("lines-header", "Lines index", "100%")}</p>',
        "\n".join(timeframes),
        f'<p>{r.link(f"https://github.com/{username}?tab=repositories", r.picture("section-watchlist", "Watchlist", "100%"), "All repositories")}'
        f"<br>{rows(projects)}</p>",
        f'<p>{r.picture("section-languages", "Languages", "100%")}<br>{rows(languages[:VISIBLE_LANGUAGES])}</p>',
        (f"<details><summary>All {len(languages)} languages</summary>\n\n<p>{rows(hidden)}</p>\n\n</details>" if hidden else ""),
        f'<p>{r.picture("section-stack", "Tech stack", "100%")}<br>{pairs(stack)}</p>',
        f'<p>{r.link(data["open_source"]["url"], r.picture("section-collabs", "Collaborations", "100%"), "Every merged pull request")}'
        f"<br>{rows(collabs)}</p>",
        f'<p>{r.link(portfolio, r.picture("section-record", "Track record", "100%"), "Portfolio")}<br>{pairs(record)}</p>',
        '<p align="right"><sub>Live public data, refreshed every 15 minutes</sub></p>',
    ])) + "\n"
    return files, readme


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/activity.json")
    parser.add_argument("--config", type=Path, default=ROOT / "profile.json")
    parser.add_argument("--output", type=Path, default=ROOT / "assets/gen")
    parser.add_argument("--base", default=LIVE_BASE, help="URL prefix for widget images in README.md")
    args = parser.parse_args()
    data = json.loads(args.data.read_text(encoding="utf-8"))
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if not data["coverage"]["complete"] or data.get("schema_version", 1) < 3:
        raise ValueError("Refusing to render an incomplete or outdated activity snapshot")
    files, readme = build(data, config, args.base)
    args.output.mkdir(parents=True, exist_ok=True)
    # The folder is fully generated; clearing it drops widgets for candles that left the chart.
    for stale in args.output.glob("*.svg"):
        if stale.name not in files:
            stale.unlink()
    for name, content in files.items():
        (args.output / name).write_text(content, encoding="utf-8", newline="\n")
    (ROOT / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    print(f"Rendered {len(files)} widgets and README.md.")


if __name__ == "__main__":
    main()
