"""Render the brokerage-app profile: SVG widgets and README.md.

Every number comes from data/activity.json; profile.json supplies names, links and
the curated achievements. Each widget is written in light/dark and desktop/mobile
variants that GitHub picks between with <picture> media queries.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from html import escape
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"
THEMES = {
    "light": dict(bg="#ffffff", card="#f6f8fa", fg="#1f2328", muted="#59636e", faint="#d8dee4",
                  grid="#eaeef2", up="#1a7f37", up_fill="#2da44e", down="#cf222e", down_fill="#e5484d",
                  flat="#8c959f", amber="#9a6700", amber_fill="#d4a72c", ink_on_amber="#1f2328",
                  icons=("#e16f24", "#8250df", "#0e8a9e", "#1a7f37")),
    "dark": dict(bg="#0d1117", card="#151b23", fg="#f0f6fc", muted="#9198a1", faint="#2a313c",
                 grid="#1f2630", up="#3fb950", up_fill="#2ea043", down="#f85149", down_fill="#da3633",
                 flat="#6e7681", amber="#e3b341", amber_fill="#d29922", ink_on_amber="#0d1117",
                 icons=("#f0883e", "#a371f7", "#39c5cf", "#3fb950")),
}
LOGO_COLORS = ("#1b2a4a", "#b4232c", "#0e7490", "#b7791f", "#6d28d9", "#334155")
LANGUAGE_COLORS = {
    "TypeScript": "#3178c6", "JavaScript": "#f1e05a", "Python": "#3572a5", "Go": "#00add8",
    "HTML": "#e34c26", "CSS": "#663399", "Java": "#b07219", "Shell": "#89e051", "Rust": "#dea584",
    "PLpgSQL": "#336790", "Batchfile": "#c1f12e", "Dockerfile": "#384d54", "PowerShell": "#012456",
    "SCSS": "#c6538c", "Vue": "#41b883", "C#": "#178600", "C++": "#f34b7d", "Kotlin": "#a97bff",
}
LANGUAGE_CODES = {"TypeScript": "TS", "JavaScript": "JS", "Python": "PY", "Go": "GO", "HTML": "HTML",
                  "CSS": "CSS", "Java": "JAVA", "Shell": "SH", "Rust": "RS", "PLpgSQL": "SQL",
                  "Batchfile": "BAT", "Dockerfile": "DKR", "PowerShell": "PS1", "C#": "CS"}
MINUS = "\u2212"
VISIBLE_LANGUAGES = 6


# ---------------------------------------------------------------- formatting

def num(value: float) -> str:
    return (MINUS if value < 0 else "") + f"{abs(round(value)):,}"


def signed(value: float, compact_values: bool = False) -> str:
    if value == 0:
        return "0"
    return ("+" if value > 0 else MINUS) + (compact(abs(value)) if compact_values else f"{abs(round(value)):,}")


def compact(value: float) -> str:
    sign, value = (MINUS if value < 0 else ""), abs(value)
    if value >= 1_000_000:
        return f"{sign}{value / 1_000_000:.1f}m"
    if value >= 10_000:
        return f"{sign}{value / 1000:.1f}k"
    return f"{sign}{round(value):,}"


def kilo(value: float) -> str:
    return f"{value / 1000:.1f}k" if abs(value) >= 1000 else f"{round(value)}"


def percent(delta: float, base: float) -> str:
    if not base:
        return ""
    value = delta / base * 100
    return ("+" if value > 0 else MINUS if value < 0 else "") + f"{abs(value):.2f}%"


def text_width(value: str, size: float, weight: int = 400) -> float:
    """Generous width estimate for system sans fonts, used only for layout."""
    width = 0.0
    for char in value:
        if char in " ":
            width += .28
        elif char in ".,:;'|!il":
            width += .3
        elif char.isdigit():
            width += .6
        elif char.isupper() or char in "★%&@MW":
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


# ---------------------------------------------------------------- SVG writer

class SVG:
    def __init__(self, width: float, height: float, theme: str, label: str, extra_css: str = ""):
        self.w, self.h, self.p = width, height, THEMES[theme]
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

    def color(self, value: str) -> str:
        return self.p.get(value, value)

    def add(self, markup: str):
        self.parts.append(markup)

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

    def sparkline(self, values, x, y, w, h, stroke, uid, fill=True, dot=True):
        values = values or [0]
        if len(values) == 1:
            values = values * 2
        lo, hi = min(values), max(values)
        span = hi - lo
        points = [(x + i / (len(values) - 1) * w,
                   y + h / 2 if not span else y + h - (v - lo) / span * h) for i, v in enumerate(values)]
        line = "M" + " L".join(f"{px:.1f} {py:.1f}" for px, py in points)
        color = self.color(stroke)
        if fill:
            self.add(f'<defs><linearGradient id="g{uid}" x1="0" y1="0" x2="0" y2="1">'
                     f'<stop offset="0" stop-color="{color}" stop-opacity=".14"/>'
                     f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>')
            self.add(f'<path d="{line} L{x + w:.1f} {y + h:.1f} L{x:.1f} {y + h:.1f} Z" fill="url(#g{uid})"/>')
        self.add(f'<path class="draw" pathLength="1" d="{line}" fill="none" stroke="{color}" '
                 'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
        if dot:
            px, py = points[-1]
            self.add(f'<circle class="pulse" cx="{px:.1f}" cy="{py:.1f}" r="3" fill="{color}"/>'
                     f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="{color}"/>')

    def logo(self, cx, cy, r, label, fill, ink="#ffffff"):
        self.add(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:g}" fill="{fill}"/>')
        size = r * (0.86 if len(label) == 1 else 0.68 if len(label) == 2 else 0.5)
        self.text(cx, cy + size * .36, label, size, ink, 700, "middle")

    def chevron(self, x, y, size=9, stroke="muted"):
        self.add(f'<path d="M{x:.1f} {y - size:.1f} L{x + size * .62:.1f} {y:.1f} L{x:.1f} {y + size:.1f}" '
                 f'fill="none" stroke="{self.color(stroke)}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>')

    def svg(self) -> str:
        return "\n".join(self.parts + ["</svg>"]) + "\n"


def ink_for(background: str) -> str:
    red, green, blue = (int(background[i:i + 2], 16) for i in (1, 3, 5))
    return "#1f2328" if (0.299 * red + 0.587 * green + 0.114 * blue) > 150 else "#ffffff"


def tone(value: float) -> str:
    return "up" if value > 0 else "down" if value < 0 else "flat"


# ---------------------------------------------------------------- derived data

class Market:
    """Daily series and summaries derived from one activity snapshot."""

    def __init__(self, data: dict, config: dict):
        self.data, self.config = data, config
        self.start, self.end = day(data["window"]["start"]), day(data["generated_at"])
        self.days = [self.start + timedelta(days=i) for i in range((self.end - self.start).days + 1)]
        self.commits = sorted(data["commits"], key=lambda row: row["timestamp"])
        self.weeks = data["weeks"]
        self.open_source = data["open_source"]

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
                    if day(when) >= self.start:
                        events[day(when)] = events.get(day(when), 0) + count
            total = self.data["stars"]["total"]
            series = self.cumulative(events, total - sum(events.values()))
        elif key == "commits":
            events = {}
            for row in self.commits:
                events[day(row["timestamp"])] = events.get(day(row["timestamp"]), 0) + 1
            series = self.cumulative(events)
        else:
            dates = [day(stamp) for repo in self.open_source["repositories"] for stamp in repo["merged_at"]]
            events = {}
            for when in dates:
                if when >= self.start:
                    events[when] = events.get(when, 0) + 1
            series = self.cumulative(events, sum(when < self.start for when in dates))
        previous = series[-8] if len(series) > 7 else series[0]
        return {"series": series, "value": series[-1], "delta": series[-1] - previous, "previous": previous}

    def languages(self) -> list[dict]:
        sizes = self.data["languages"]["bytes"]
        total = sum(sizes.values()) or 1
        net: dict[str, int] = {}
        for row in self.commits:
            for language, (added, deleted) in row.get("languages", {}).items():
                net[language] = net.get(language, 0) + added - deleted
        return [{"name": name, "bytes": size, "share": size / total * 100, "net": net.get(name, 0)}
                for name, size in sizes.items()]

    def repo_lines(self, repository: str) -> int:
        return sum(row["additions"] - row["deletions"] for row in self.commits if row["repository"] == repository)

    def contribution_series(self, events: dict[date, int], points: int = 48) -> list[int]:
        """Cumulative contributions from the first one to the snapshot date."""
        if not events:
            return [0, 0]
        first = min(events)
        span = max((self.end - first).days, 1)
        series = []
        for i in range(points + 1):
            cutoff = first + timedelta(days=span * i / points)
            series.append(sum(count for when, count in events.items() if when <= cutoff))
        return series

    def stars_of(self, repository: str) -> int:
        return next((row["stars"] for row in self.data["stars"]["repositories"]
                     if row["name"].lower() == repository.lower()), 0)


# ---------------------------------------------------------------- widgets

def tape(market: Market, theme: str, mobile: bool) -> SVG:
    w, h, size = (400, 46, 17) if mobile else (846, 40, 14)
    items = []
    for key, label in (("stars", "STARS"), ("commits", "COMMITS 90D"), ("prs", "MERGED PRS")):
        index = market.index(key)
        items.append((label, num(index["value"]), signed(index["delta"]), tone(index["delta"])))
    net, last = market.data["totals"]["net_lines"], market.weeks[-1]
    items.append(("LINES 90D", num(net), signed(last["close"] - last["open"]), tone(last["close"] - last["open"])))
    for row in market.languages()[:4]:
        items.append((LANGUAGE_CODES.get(row["name"], row["name"][:3].upper()), f"{row['share']:.1f}%",
                      signed(row["net"], True), tone(row["net"])))
    for project in market.config["projects"]:
        lines = market.repo_lines(project["repository"])
        commits = sum(market.data["lifetime_commit_days"].get(project["repository"], {}).values())
        items.append((project["ticker"], str(commits), signed(lines, True), tone(lines)))
    pieces, x = [], 0.0
    for label, value, change, direction in items:
        pieces.append((x, label, value, change, direction))
        x += sum(text_width(part, size, 600) for part in (label, value, change)) + size * 1.4 + size * 2.6
    loop = x
    duration = loop / (30 if mobile else 38)
    s = SVG(w, h, theme, "Live tape: " + "; ".join(f"{a} {b} ({c})" for a, b, c, _ in items),
            f'.run{{animation:run {duration:.0f}s linear infinite}}@keyframes run{{to{{transform:translateX(-{loop:.1f}px)}}}}')
    s.rect(0, 0, w, h, "bg")
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
            px += text_width(value, size, 600) + size * .6
            arrow = "▲" if direction == "up" else "▼" if direction == "down" else "■"
            s.text(px, baseline, f"{arrow} {change}", size, direction, 600)
    s.add("</g>")
    return s


FOCUS_ICONS = (
    # sparkle, agent loop, stacked layers, chip
    "M13 4 L15 11 L22 13 L15 15 L13 22 L11 15 L4 13 L11 11 Z",
    "M7 9 A7 7 0 0 1 19.5 10 M19 17 A7 7 0 0 1 6.5 16 M19.5 6 V10 H15.5 M6.5 20 V16 H10.5",
    "M13 5 L22 9.5 L13 14 L4 9.5 Z M4 13.5 L13 18 L22 13.5 M4 17.5 L13 22 L22 17.5",
    "M8 8 H18 V18 H8 Z M11 11 H15 V15 H11 Z M11 4 V8 M15 4 V8 M11 18 V22 M15 18 V22 M4 11 H8 M4 15 H8 M18 11 H22 M18 15 H22",
)


def identity(market: Market, theme: str, mobile: bool) -> SVG:
    config = market.config
    w = 400 if mobile else 846
    pad, pill_h, pill_size, chip_size = (18, 52, 19, 16) if mobile else (24, 46, 16, 13)
    # Lay out focus pills and stack chips first so the canvas height follows the content.
    def flow(labels, height, font, extra, gap, top):
        placed, x, y = [], pad, top
        for label in labels:
            width = text_width(label, font, 500) + extra
            if x + width > w - pad and x > pad:
                x, y = pad, y + height + gap
            placed.append((x, y, width, label))
            x += width + gap
        return placed, y + height
    head = 104 if mobile else 100
    if mobile:
        # Phones get an app-style shortcut grid: icon tile above a short label.
        cell = (w - 2 * pad) / len(config["focus"])
        pills = [(pad + i * cell, head, cell, label) for i, label in enumerate(config["focus"])]
        bottom = head + 58 + 12 + 2 * 21
    else:
        pills, bottom = flow(config["focus"], pill_h, pill_size, pill_h + 22, 10, head)
    chips, bottom = flow(config["stack"], 32 if mobile else 28, chip_size, 22, 8, bottom + 16)
    h = bottom + 8
    s = SVG(w, h, theme, f"{config['display_name']}, {config['role']}. Focus: {', '.join(config['focus'])}. "
            f"Stack: {', '.join(config['stack'])}.")
    s.rect(0, 0, w, h, "bg")
    r = 32 if mobile else 30
    cx, cy = pad + r, (44 if mobile else 46)
    s.add(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#13233a"/><circle cx="{cx}" cy="{cy}" r="{r - 3}" fill="none" '
          f'stroke="#e3b341" stroke-width="1.5"/>')
    s.text(cx, cy + r * .4, "E", r * 1.12, "#e3b341", 400, "middle", font_family="Georgia,'Times New Roman',serif")
    tx = cx + r + 16
    s.text(tx, cy - 3, config["display_name"], 30 if mobile else 30, "fg", 700)
    dot_y = cy + (22 if mobile else 21)
    s.add(f'<circle class="pulse" cx="{tx + 5}" cy="{dot_y - 5}" r="4" fill="{s.color("up")}"/>'
          f'<circle cx="{tx + 5}" cy="{dot_y - 5}" r="4" fill="{s.color("up")}"/>')
    s.text(tx + 16, dot_y, config["role"], 18 if mobile else 16, "muted", 500)
    if not mobile:
        label = config["portfolio"].split("//")[-1].strip("/")
        bw = text_width(label, 14, 600) + 50
        s.rect(w - pad - bw, cy - 18, bw, 36, "card", 18)
        s.text(w - pad - bw + 18, cy + 5, label, 14, "fg", 600)
        s.chevron(w - pad - 20, cy, 6, "fg")
    for i, (x, y, width, label) in enumerate(pills):
        color = s.p["icons"][i % len(s.p["icons"])]
        if mobile:
            tile = 58
            s.rect(x + (width - tile) / 2, y, tile, tile, "card", 16)
            box, bx, by = 32, x + (width - 32) / 2, y + 13
        else:
            s.rect(x, y, width, pill_h, "card", pill_h / 2)
            box, bx, by = pill_h - 18, x + 9, y + 9
        s.rect(bx, by, box, box, "bg", 7, stroke=color, stroke_width="1.6")
        s.add(f'<path d="{FOCUS_ICONS[i % len(FOCUS_ICONS)]}" transform="translate({bx + 1:.1f} {by + 1:.1f}) '
              f'scale({(box - 2) / 26:.3f})" fill="none" stroke="{color}" stroke-width="{2.2 * 26 / (box - 2):.2f}" '
              'stroke-linecap="round" stroke-linejoin="round"/>')
        if mobile:
            for j, part in enumerate(wrap(label, 16, width - 6, 500)[:2]):
                s.text(x + width / 2, y + 58 + 24 + j * 21, part, 16, "fg", 500, "middle")
        else:
            s.text(bx + box + 10, y + pill_h / 2 + pill_size * .36, label, pill_size, "fg", 500)
    chip_h = 32 if mobile else 28
    for x, y, width, label in chips:
        s.rect(x + .5, y + .5, width - 1, chip_h - 1, "bg", 8, stroke=s.color("faint"))
        s.text(x + width / 2, y + chip_h / 2 + chip_size * .36, label, chip_size, "muted", 500, "middle")
    return s


INDEX_TILES = (("stars", "Stars", "owned + collab"), ("commits", "Commits", "90 days"), ("prs", "Merged PRs", "external"))


def index_tile(market: Market, key: str, theme: str, mobile: bool) -> SVG:
    title, hint = next((title, hint) for k, title, hint in INDEX_TILES if k == key)
    index = market.index(key)
    color = tone(index["delta"])
    w, h = (200, 214) if mobile else (282, 178)
    s = SVG(w, h, theme, f"{title}: {num(index['value'])}, {signed(index['delta'])} in 7 days")
    s.rect(0, 0, w, h, "bg")
    s.rect(4, 4, w - 8, h - 8, "card", 16 if mobile else 14)
    x = 20 if mobile else 22
    if mobile:
        s.text(x, 44, title, 22, "fg", 500)
        s.text(x, 90, num(index["value"]), 36, color, 700)
        s.text(x, 122, f"{signed(index['delta'])} {percent(index['delta'], index['previous'])}".strip(), 19, color, 500)
        s.sparkline(index["series"], x, 140, w - 2 * x, 46, color, f"{key}{theme}m")
    else:
        s.text(x, 38, title, 18, "fg", 500)
        s.text(w - x, 38, hint, 12, "muted", 500, "end")
        s.text(x, 78, num(index["value"]), 32, color, 700)
        s.text(x, 104, f"{signed(index['delta'])}  {percent(index['delta'], index['previous'])}  7D".strip(), 14, color, 500)
        s.sparkline(index["series"], x, 118, w - 2 * x, 40, color, f"{key}{theme}")
    return s


# ---------------------------------------------------------------- candle chart

class ChartGeometry:
    def __init__(self, market: Market, mobile: bool):
        self.weeks = market.weeks
        self.n = len(self.weeks)
        self.axis_pct = 12.0
        self.week_pct = round((99.6 - self.axis_pct) / self.n, 3)
        self.unit = (52 / self.week_pct) if mobile else 8.46   # canvas units per percent of README width
        self.week_w = self.week_pct * self.unit
        self.axis_w = self.axis_pct * self.unit
        self.mobile = mobile
        if mobile:
            self.h, self.top, self.bottom, self.vol_top, self.vol_bottom = 820, 40, 560, 610, 730
        else:
            self.h, self.top, self.bottom, self.vol_top, self.vol_bottom = 392, 26, 262, 288, 348
        values = [0] + [week[k] for week in self.weeks for k in ("high", "low")]
        lo, hi = min(values), max(values)
        span = max(hi - lo, 10)
        power = 10 ** math.floor(math.log10(span / 4))
        self.step = next(n * power for n in (1, 2, 2.5, 5, 10) if n * power >= span / 4)
        # Headroom above the high keeps its callout inside the plot.
        self.lo, self.hi = lo - span * .05, hi + span * .1
        self.max_commits = max([week["commits"] for week in self.weeks] + [1])
        self.high_index = max(range(self.n), key=lambda i: self.weeks[i]["high"])
        self.low_index = min(range(self.n), key=lambda i: self.weeks[i]["low"])
        # Mobile shows month names where a month starts, at least two weeks apart.
        self.month_labels, last = set(), -9
        for i, week in enumerate(self.weeks):
            start = day(week["start"])
            first_is_stub = i == 0 and self.n > 1 and day(self.weeks[1]["start"]).month != start.month
            if not first_is_stub and (i == 0 or day(self.weeks[i - 1]["start"]).month != start.month) and i - last >= 2:
                self.month_labels.add(i)
                last = i

    def y(self, value: float) -> float:
        return self.bottom - (value - self.lo) / (self.hi - self.lo) * (self.bottom - self.top)

    def ticks(self):
        return [k * self.step for k in range(math.ceil(self.lo / self.step), math.floor(self.hi / self.step) + 1)]


def week_direction(week: dict) -> str:
    if not week["commits"]:
        return "flat"
    return tone(week["close"] - week["open"]) if week["close"] != week["open"] else "up"


def week_title(week: dict) -> str:
    start = day(week["start"])
    commits = week["commits"]
    if not commits:
        return f"Week of {start:%d %b %Y}: no commits; index flat at {num(week['close'])}"
    return (f"Week of {start:%d %b %Y}: {commits} commit{'s' if commits != 1 else ''}, "
            f"+{week['additions']:,} / {MINUS}{week['deletions']:,} lines, close {num(week['close'])}")


def chart_week(market: Market, index: int, theme: str, mobile: bool) -> SVG:
    g = ChartGeometry(market, mobile)
    week = g.weeks[index]
    w = g.week_w
    css = ('.rise{transform-box:fill-box;transform-origin:50% 100%;animation:rise .7s cubic-bezier(.2,.8,.2,1) both;'
           f'animation-delay:{index * .07:.2f}s}}@keyframes rise{{from{{transform:scaleY(0);opacity:0}}}}')
    s = SVG(w, g.h, theme, week_title(week), css)
    s.rect(0, 0, w, g.h, "bg")
    for tick in g.ticks():
        s.line(0, g.y(tick), w, g.y(tick), "grid")
    s.line(0, g.vol_bottom + .5, w, g.vol_bottom + .5, "grid")
    last = g.weeks[-1]
    last_tone = tone(last["close"] - last["open"])
    dash = "7 5" if mobile else "4 3"
    s.line(0, g.y(last["close"]), w, g.y(last["close"]), last_tone, 2 if mobile else 1, stroke_dasharray=dash, opacity=".75")
    cx, body = w / 2, w * .58
    direction = week_direction(week)
    stroke = 3 if mobile else 1.5
    if week["commits"]:
        top, bottom = sorted((g.y(week["open"]), g.y(week["close"])))
        if bottom - top < 2:
            top, bottom = top - 1, bottom + 1
        s.add('<g class="rise">')
        s.line(cx, g.y(week["high"]), cx, g.y(week["low"]), direction, stroke)
        if direction == "up":
            s.rect(cx - body / 2 + stroke / 2, top, body - stroke, bottom - top, "bg", 1,
                   stroke=s.color("up"), stroke_width=stroke)
        else:
            s.rect(cx - body / 2, top, body, bottom - top, "down", 1)
        s.add("</g>")
    else:
        s.line(cx - body / 2, g.y(week["close"]), cx + body / 2, g.y(week["close"]), "flat", stroke)
    if not mobile:
        if index == g.high_index and week["high"]:
            s.text(cx, g.y(week["high"]) - 8, num(week["high"]), 11, "muted", 600, "middle")
        if index == g.low_index and week["low"] < 0:
            s.text(cx, g.y(week["low"]) + 16, num(week["low"]), 11, "muted", 600, "middle")
    if week["commits"]:
        height = week["commits"] / g.max_commits * (g.vol_bottom - g.vol_top)
        fill = "up_fill" if direction == "up" else "down_fill"
        s.rect(cx - body / 2, g.vol_bottom - height, body, max(height, 2), fill, 1, opacity=".9")
    if index == g.n - 1:
        s.add(f'<circle class="pulse" cx="{cx:.1f}" cy="{g.y(week["close"]):.1f}" r="{4 if mobile else 3}" '
              f'fill="{s.color(direction)}"/>')
    start = day(week["start"])
    if mobile:
        if index in g.month_labels:
            s.text(3, g.h - 34, f"{start:%b}", 27, "muted", 500)
    elif index % 2 == 0:
        s.text(cx, g.h - 14, f"{start:%b} {start.day}", 11, "muted", 500, "middle")
    return s


def chart_axis(market: Market, theme: str, mobile: bool) -> SVG:
    g = ChartGeometry(market, mobile)
    w = g.axis_w
    s = SVG(w, g.h, theme, "Price axis for the lines index; dashed line marks the latest close")
    s.rect(0, 0, w, g.h, "bg")
    size = 28 if mobile else 11
    last = g.weeks[-1]
    color = tone(last["close"] - last["open"])
    tag_h = 44 if mobile else 20
    y = g.y(last["close"])
    for tick in g.ticks():
        s.line(0, g.y(tick), w, g.y(tick), "grid")
        label_y = g.y(tick) - (8 if mobile else 4)
        if not (label_y > y - tag_h / 2 - 2 and label_y - size < y + tag_h / 2 + 2):
            s.text(w - (8 if mobile else 6), label_y, compact(tick), size, "muted", 500, "end")
    s.line(0, g.vol_bottom + .5, w, g.vol_bottom + .5, "grid")
    s.rect(0, y - tag_h / 2, w - 2, tag_h, color, 4 if mobile else 3)
    s.text((w - 2) / 2, y + size * .36, compact(last["close"]), size, "#ffffff", 700, "middle")
    s.text(w - (8 if mobile else 6), g.vol_top + size, f"VOL {g.max_commits}", size, "muted", 500, "end")
    return s


def chart_header(market: Market, theme: str, mobile: bool) -> SVG:
    last = market.weeks[-1]
    change = last["close"] - last["open"]
    color = tone(change)
    totals = market.data["totals"]
    highs = max(week["high"] for week in market.weeks)
    lows = min(week["low"] for week in market.weeks)
    w, h = (400, 150) if mobile else (846, 104)
    s = SVG(w, h, theme, f"Lines index {num(last['close'])}, {signed(change)} this week. "
            f"Weekly candles of net lines over {market.data['window']['days']} days.")
    s.rect(0, 0, w, h, "bg")
    pad = 18 if mobile else 24
    title_size = 22 if mobile else 18
    s.text(pad, 34 if mobile else 30, "Lines index", title_size, "fg", 600)
    ix = pad + text_width("Lines index", title_size, 600) + 12
    iy = (34 if mobile else 30) - title_size * .36
    s.add(f'<circle cx="{ix:.1f}" cy="{iy:.1f}" r="{title_size * .42:.1f}" fill="none" stroke="{s.color("muted")}" stroke-width="1.4"/>')
    s.text(ix, iy + title_size * .3, "i", title_size * .62, "muted", 700, "middle", font_family="Georgia,serif")
    if mobile:
        s.text(pad, 82, num(last["close"]), 38, color, 700)
        s.text(pad, 114, f"{signed(change)}  {percent(change, last['open'])}  this week".strip(), 18, color, 500)
        s.text(pad, 140, f"High {compact(highs)}   Low {compact(lows)}   Vol {totals['commits']}", 16, "muted", 500)
    else:
        s.text(pad, 72, num(last["close"]), 32, color, 700)
        vx = pad + text_width(num(last["close"]), 32, 700) + 14
        s.text(vx, 72, f"{signed(change)}  {percent(change, last['open'])}  this week".strip(), 16, color, 500)
        stats = (("High", compact(highs)), ("Low", compact(lows)), ("Vol", str(totals["commits"])),
                 ("+ lines", compact(totals["additions"])), (f"{MINUS} lines", compact(totals["deletions"])))
        x = w - pad
        for label, value in reversed(stats):
            s.text(x, 52, value, 15, "fg", 600, "end")
            s.text(x, 74, label, 12, "muted", 500, "end")
            x -= max(text_width(value, 15, 600), text_width(label, 12, 500)) + 26
        s.text(pad, 96, "Weekly candles. Added lines lift the index, deleted lines drop it. Volume is commits.",
               12, "muted", 500)
    return s


# ---------------------------------------------------------------- lists

LIST_LAYOUTS = {
    # name/sub start, sparkline (x, width), value right edge, badge (x, width)
    False: dict(w=846, row_h=80, logo=(46, 22), text_x=84, name=19, sub=13, spark=(352, 170),
                value_x=684, value=20, badge=(702, 120), badge_size=17, pad=24),
    True: dict(w=400, row_h=104, logo=(34, 20), text_x=64, name=21, sub=16, spark=(206, 50),
               value_x=316, value=20, badge=(326, 66), badge_size=16, pad=16),
}


def section_header(title: str, columns: tuple[str, ...], theme: str, mobile: bool) -> SVG:
    """Section title with a chevron; list sections also get a column legend.

    columns: (first, second, third desktop, third mobile) or empty for tile sections.
    """
    L = LIST_LAYOUTS[mobile]
    w = L["w"]
    h = (88 if mobile else 74) if columns else (54 if mobile else 48)
    s = SVG(w, h, theme, title)
    s.rect(0, 0, w, h, "bg")
    size = 28 if mobile else 24
    s.text(L["pad"], 40 if mobile else 34, title, size, "fg", 700)
    s.chevron(w - L["pad"] - 8, (40 if mobile else 34) - size * .36, 8 if mobile else 7)
    if columns:
        small, y = (15 if mobile else 12), h - 12
        s.text(L["pad"], y, columns[0], small, "muted", 500)
        s.text(L["value_x"], y, columns[1], small, "muted", 500, "end")
        s.text(w - L["pad"], y, columns[3 if mobile else 2], small, "muted", 500, "end")
        s.line(L["pad"], h - .5, w - L["pad"], h - .5, "faint")
    return s


def list_row(theme: str, mobile: bool, *, logo: str, logo_fill: str, name: str, sub: str, series: list | None,
             spark_tone: str, value: str, value_sub: str, badge: str, badge_fill: str, badge_ink: str = "#ffffff",
             label: str, bar: tuple[float, str] | None = None, uid: str = "") -> SVG:
    L = LIST_LAYOUTS[mobile]
    w, h = L["w"], L["row_h"]
    s = SVG(w, h, theme, label)
    s.rect(0, 0, w, h, "bg")
    lx, r = L["logo"]
    s.logo(lx, h / 2, r, logo, logo_fill, ink_for(logo_fill))
    room = L["spark"][0] - L["text_x"] - 14
    s.text(L["text_x"], h / 2 - 4, fit(name, L["name"], room, 500), L["name"], "fg", 500)
    s.text(L["text_x"], h / 2 + L["sub"] + 6, fit(sub, L["sub"], room), L["sub"], "muted", 400)
    sx, sw = L["spark"]
    if series is not None:
        s.sparkline(series, sx, h / 2 - 22, sw, 40, spark_tone, uid + theme + ("m" if mobile else ""), dot=False)
    if bar is not None:
        share, color = bar
        bh = 8 if mobile else 6
        s.rect(sx, h / 2 - bh / 2, sw, bh, "grid", bh / 2)
        s.rect(sx, h / 2 - bh / 2, max(sw * share / 100, bh), bh, color, bh / 2)
    s.text(L["value_x"], h / 2 - 2, value, L["value"], "fg", 600, "end")
    s.text(L["value_x"], h / 2 + L["sub"] + 6, value_sub, L["sub"] - 1, "muted", 400, "end")
    bx, bw = L["badge"]
    bh = 40 if mobile else 38
    s.rect(bx, h / 2 - bh / 2, bw, bh, badge_fill, 6)
    size = L["badge_size"]
    s.text(bx + bw / 2, h / 2 + size * .36, fit(badge, size, bw - 8, 700), size, badge_ink, 700, "middle")
    s.line(L["pad"], h - .5, w - L["pad"], h - .5, "grid")
    return s


def month_label(when: date) -> str:
    return f"{when:%b %Y}"


def project_rows(market: Market) -> list[tuple[str, callable, str, str]]:
    rows = []
    for i, project in enumerate(market.config["projects"]):
        repository = project["repository"]
        days = {day(k): v for k, v in market.data["lifetime_commit_days"].get(repository, {}).items()}
        commits = sum(days.values())
        lines = market.repo_lines(repository)
        series = market.contribution_series(days)
        since = month_label(min(days)) if days else "no commits"
        label = (f"{project['name']} ({project['ticker']}): {commits} authored commits since {since}; "
                 f"{signed(lines)} net lines in the last {market.data['window']['days']} days")

        def render(theme, mobile, project=project, i=i, commits=commits, lines=lines, series=series,
                   since=since, label=label):
            p = THEMES[theme]
            badge_fill = p["up_fill"] if lines > 0 else p["down_fill"] if lines < 0 else p["flat"]
            return list_row(theme, mobile, logo=project["ticker"][:1], logo_fill=LOGO_COLORS[i % len(LOGO_COLORS)],
                            name=project["name"], sub=project["ticker"], series=series, spark_tone="up",
                            value=f"{commits:,}", value_sub=f"since {since}" if not mobile else since.split()[-1],
                            badge=signed(lines, True), badge_fill=badge_fill, label=label, uid=f"p{i}")
        rows.append((f"project-{i}", render, label, f"https://github.com/{repository}"))
    return rows


def collaboration_rows(market: Market) -> list[tuple[str, callable, str, str]]:
    rows, username = [], market.data["github_username"]
    for i, entry in enumerate(market.config["collaborations"]):
        entry = entry if isinstance(entry, dict) else {"repository": entry}
        repository = entry["repository"]
        owner, name = repository.split("/")
        if owner.lower() == username.lower():
            days = {day(k): v for k, v in market.data["lifetime_commit_days"].get(repository, {}).items()}
            unit, link = "commits", f"https://github.com/{repository}/commits?author={username}"
        else:
            source = next((row for row in market.open_source["repositories"] if row["name"].lower() == repository.lower()), None)
            days = {}
            for stamp in (source or {}).get("merged_at", []):
                days[day(stamp)] = days.get(day(stamp), 0) + 1
            unit = "merged PRs"
            link = f"https://github.com/{repository}/pulls?q=is%3Apr+is%3Amerged+author%3A{username}"
        count, stars = sum(days.values()), market.stars_of(repository)
        series = market.contribution_series(days)
        title = entry.get("name", name)
        label = f"{title} ({repository}): {count} {unit}; repository has {stars:,} stars"

        def render(theme, mobile, i=i, owner=owner, title=title, unit=unit, count=count, stars=stars,
                   series=series, label=label, logo=entry.get("logo", name[:2].upper())):
            p = THEMES[theme]
            return list_row(theme, mobile, logo=logo, logo_fill=LOGO_COLORS[(i + 2) % len(LOGO_COLORS)],
                            name=title, sub=owner, series=series, spark_tone="up", value=f"{count:,}",
                            value_sub=unit, badge=f"★ {kilo(stars) if mobile else f'{stars:,}'}",
                            badge_fill=p["amber_fill"], badge_ink=p["ink_on_amber"], label=label, uid=f"c{i}")
        rows.append((f"collab-{i}", render, label, link))
    return rows


def language_rows(market: Market) -> list[tuple[str, callable, str, str]]:
    rows = []
    days = market.data["window"]["days"]
    for i, row in enumerate(market.languages()):
        code = LANGUAGE_CODES.get(row["name"], row["name"][:3].upper())
        color = LANGUAGE_COLORS.get(row["name"], "#6e7781")
        share = "<0.1%" if row["share"] < .1 else f"{row['share']:.1f}%"
        label = (f"{row['name']}: {share} of language bytes across selected public repositories; "
                 f"{signed(row['net'])} net lines in {days} days")

        def render(theme, mobile, row=row, code=code, color=color, share=share, label=label):
            p = THEMES[theme]
            fill = p["up_fill"] if row["net"] > 0 else p["down_fill"] if row["net"] < 0 else p["flat"]
            return list_row(theme, mobile, logo=code[:3], logo_fill=color, name=row["name"],
                            sub=code if mobile else f"{code} · {compact(row['bytes'] / 1024)} KB", series=None, spark_tone="up",
                            value=share, value_sub="of bytes", badge=signed(row["net"], True), badge_fill=fill,
                            label=label, bar=(row["share"], color))
        rows.append((f"lang-{i}", render, label, None))
    return rows


MEDAL = "M10 2 L14 9 M22 2 L18 9 M16 30 A9 9 0 1 0 16 12 A9 9 0 1 0 16 30 Z M16 16 L17.6 19.4 L21.2 19.8 L18.5 22.2 L19.3 25.8 L16 24 L12.7 25.8 L13.5 22.2 L10.8 19.8 L14.4 19.4 Z"
TROPHY = "M9 4 H23 V11 A7 7 0 0 1 9 11 Z M9 6 H4 V8 A5 5 0 0 0 9.5 13 M23 6 H28 V8 A5 5 0 0 1 22.5 13 M16 18 V24 M10 28 H22 M12 24 H20 V28"


def achievement_tile(achievement: dict, i: int, theme: str, mobile: bool) -> SVG:
    w, h = (200, 168) if mobile else (421, 112)
    s = SVG(w, h, theme, f"{achievement['rank']}, {achievement['event']} ({achievement['tag']})")
    s.rect(0, 0, w, h, "bg")
    s.rect(4, 4, w - 8, h - 8, "card", 16 if mobile else 14)
    color = s.p["icons"][i % len(s.p["icons"])]
    box = 44 if mobile else 52
    bx, by = (18, 18) if mobile else (22, (h - 52) / 2)
    s.rect(bx, by, box, box, "bg", 12, stroke=color, stroke_width="1.6")
    s.add(f'<path d="{TROPHY if i == 0 else MEDAL}" transform="translate({bx + box * .14:.1f} {by + box * .14:.1f}) '
          f'scale({box * .72 / 32:.3f})" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>')
    tag_size = 15 if mobile else 12
    tag_w = text_width(achievement["tag"], tag_size, 600) + 18
    tag_h = 26 if mobile else 22
    tx, ty = w - 18 - tag_w, (18 if mobile else 18)
    s.rect(tx, ty, tag_w, tag_h, "bg", tag_h / 2)
    s.text(tx + tag_w / 2, ty + tag_h / 2 + tag_size * .36, achievement["tag"], tag_size, "muted", 600, "middle")
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

def picture(name: str, alt: str, width: str, title: str | None = None) -> str:
    base = f"assets/gen/{name}"
    hover = f' title="{escape(title)}"' if title else ""
    return (f'<picture><source media="(prefers-color-scheme: dark) and (max-width: 600px)" srcset="{base}-dark-m.svg">'
            f'<source media="(max-width: 600px)" srcset="{base}-light-m.svg">'
            f'<source media="(prefers-color-scheme: dark)" srcset="{base}-dark.svg">'
            f'<img src="{base}-light.svg" width="{width}" alt="{escape(alt)}"{hover}></picture>')


def linked(href: str | None, inner: str, title: str | None = None) -> str:
    if not href:
        return inner
    hover = f' title="{escape(title)}"' if title else ""
    return f'<a href="{escape(href)}"{hover}>{inner}</a>'


def build(data: dict, config: dict, out: Path) -> tuple[dict[str, str], str]:
    market = Market(data, config)
    files: dict[str, str] = {}

    def emit(name, render):
        for theme in THEMES:
            for mobile in (False, True):
                files[f"{name}-{theme}{'-m' if mobile else ''}.svg"] = render(theme, mobile).svg()

    emit("tape", lambda t, m: tape(market, t, m))
    emit("identity", lambda t, m: identity(market, t, m))
    for key, *_ in INDEX_TILES:
        emit(f"index-{key}", lambda t, m, key=key: index_tile(market, key, t, m))
    emit("chart-header", lambda t, m: chart_header(market, t, m))
    emit("chart-axis", lambda t, m: chart_axis(market, t, m))
    for i in range(len(market.weeks)):
        emit(f"chart-week-{i:02d}", lambda t, m, i=i: chart_week(market, i, t, m))
    period = f"{data['window']['days']}D"
    sections = {
        "watchlist": ("Watchlist", ("Project", "Commits", f"{period} lines", period)),
        "languages": ("Languages", ("Language", "Share", f"{period} lines", period)),
        "collabs": ("Collaborations", ("Repository", "Contributions", "Repo stars", "Stars")),
        "record": ("Track record", ()),
    }
    for key, (title, columns) in sections.items():
        emit(f"section-{key}", lambda t, m, title=title, columns=columns: section_header(title, columns, t, m))
    projects, collabs, languages = project_rows(market), collaboration_rows(market), language_rows(market)
    for name, render, *_ in projects + collabs + languages:
        emit(name, render)
    for i, achievement in enumerate(config["achievements"]):
        emit(f"record-{i}", lambda t, m, a=achievement, i=i: achievement_tile(a, i, t, m))

    portfolio, username = config["portfolio"], data["github_username"]
    g = ChartGeometry(market, False)
    stamp = data["generated_at"][:10]
    rows = lambda items: "<br>".join(linked(href, picture(name, label, "100%", label), label if href else None)
                                     for name, _, label, href in items)
    index_links = {"stars": f"https://github.com/{username}?tab=repositories&sort=stargazers",
                   "commits": week_search(username, market.start, market.end), "prs": data["open_source"]["url"]}
    tiles = "".join(linked(index_links[key], picture(f"index-{key}", tile_alt(market, key), "33.2%", tile_alt(market, key)),
                           tile_alt(market, key)) for key, *_ in INDEX_TILES)
    weeks = "".join(linked(week_search(username, day(week["start"]), day(week["end"])),
                           picture(f"chart-week-{i:02d}", week_title(week), f"{g.week_pct}%", week_title(week)),
                           week_title(week)) for i, week in enumerate(market.weeks))
    axis = linked("data/activity.json", picture("chart-axis", "Price axis and latest close", f"{g.axis_pct}%",
                                              "Snapshot data and methodology"), "Snapshot data and methodology")
    record = [linked(a["url"], picture(f"record-{i}", f"{a['rank']}: {a['event']}", "49.8%",
                                       f"{a['rank']} · {a['event']} · {a['tag']}"), f"{a['rank']} · {a['event']}")
              for i, a in enumerate(config["achievements"])]
    record_rows = "<br>".join("".join(record[i:i + 2]) for i in range(0, len(record), 2))
    hidden = languages[VISIBLE_LANGUAGES:]
    banner = '<img src="assets/nyse-banner.png" width="100%" alt="The New York Stock Exchange facade at dusk">'
    who = f"{config['display_name']}, {config['role']}"
    readme = "\n\n".join(filter(None, [
        "<!-- Generated by scripts/render_profile.py from profile.json and data/activity.json. Edit those, not this file. -->",
        f'<p>{linked(portfolio, banner, "Portfolio")}'
        f'<br>{linked("data/activity.json", picture("tape", "Scrolling tape of profile indexes", "100%"), "Snapshot data")}</p>',
        f'<p>{linked(portfolio, picture("identity", who, "100%", "Open portfolio"), "Open portfolio")}</p>',
        f"<p>{tiles}</p>",
        f'<p>{linked("data/activity.json", picture("chart-header", "Lines index summary", "100%", "Snapshot data and methodology"))}'
        f"<br>{weeks}{axis}</p>",
        f'<p>{linked(f"https://github.com/{username}?tab=repositories", picture("section-watchlist", "Watchlist", "100%"), "All repositories")}'
        f"<br>{rows(projects)}</p>",
        f'<p>{linked(f"https://github.com/{username}?tab=repositories", picture("section-languages", "Languages", "100%"), "All repositories")}'
        f"<br>{rows(languages[:VISIBLE_LANGUAGES])}</p>",
        (f"<details><summary>All {len(languages)} languages</summary>\n\n<p>{rows(hidden)}</p>\n\n</details>" if hidden else ""),
        f'<p>{linked(data["open_source"]["url"], picture("section-collabs", "Collaborations", "100%"), "Every merged external pull request")}'
        f"<br>{rows(collabs)}</p>",
        f'<p>{linked(portfolio, picture("section-record", "Track record", "100%"), "More on the portfolio")}'
        f"<br>{record_rows}</p>",
        f'<p align="right"><sub>Snapshot {stamp} UTC · public data only · '
        f'<a href="data/activity.json">snapshot data</a></sub></p>',
    ])) + "\n"
    return files, readme


def tile_alt(market: Market, key: str) -> str:
    index = market.index(key)
    detail = {
        "stars": f"stars across {len(market.data['stars']['repositories'])} public repositories: mine plus external repos with my merged PRs",
        "commits": f"authored, non-merge commits in {market.data['window']['days']} days",
        "prs": "merged public pull requests to repositories I don't own",
    }[key]
    return f"{num(index['value'])} {detail}; {signed(index['delta'])} in the last 7 days"


def week_search(username: str, first: date, last: date) -> str:
    """GitHub commit search for a date range in my own public repositories (profile repo excluded)."""
    query = f"author:{username} user:{username} -repo:{username}/{username} committer-date:{first}..{last}"
    return "https://github.com/search?type=commits&q=" + query.replace(":", "%3A").replace(" ", "+").replace("/", "%2F")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/activity.json")
    parser.add_argument("--config", type=Path, default=ROOT / "profile.json")
    parser.add_argument("--output", type=Path, default=ROOT / "assets/gen")
    args = parser.parse_args()
    data = json.loads(args.data.read_text(encoding="utf-8"))
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if not data["coverage"]["complete"] or data.get("schema_version", 1) < 2:
        raise ValueError("Refusing to render an incomplete or outdated activity snapshot")
    files, readme = build(data, config, args.output)
    args.output.mkdir(parents=True, exist_ok=True)
    # The folder is fully generated; clearing it drops widgets for weeks that left the window.
    for stale in args.output.glob("*.svg"):
        if stale.name not in files:
            stale.unlink()
    for name, content in files.items():
        (args.output / name).write_text(content, encoding="utf-8", newline="\n")
    (ROOT / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    print(f"Rendered {len(files)} widgets and README.md.")


if __name__ == "__main__":
    main()
