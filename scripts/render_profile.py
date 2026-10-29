"""Render self-contained, GitHub-safe SVGs from the checked-in public snapshot."""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PALETTES = {
    "dark": dict(bg="#101d2d", fg="#edf3f8", muted="#9cb0c4", rule="#2a3c50", up="#80d1b6", down="#e69c93", gold="#d0b879"),
    "light": dict(bg="#f3f6fa", fg="#13243b", muted="#52657c", rule="#d3dde7", up="#14745b", down="#a63f3e", gold="#85661c"),
}
PROJECTS = [
    ("dgx", "DGX", "DGX Spark Platform", "Local AI. Your hardware. Your rules.", "Web chat, API access and a gateway for local inference.", "Go / TypeScript / Ollama / PostgreSQL", "Infrastructure"),
    ("needle", "NDL", "Needle", "See it. Find it.", "Point at a product; an AI shopping assistant finds matches.", "React / TypeScript / Chrome MV3 / AI SDK", "AI Grand Prix · Top 10"),
    ("entryx", "ENT", "EntryX", "A different kind of ticket exchange.", "NFT ticketing and RLUSD payments on XRPL Testnet.", "Next.js / React / XRPL", "Fintech prototype"),
    ("whatnets", "NET", "WhatNETS", "Payments, inside the conversation.", "A WhatsApp-style prototype with NETS QR payment flows.", "React / JavaScript / NETS QR", "Payment prototype"),
]


class SVG:
    def __init__(self, width, height, theme, title, description):
        self.w, self.h, self.p = width, height, PALETTES[theme]
        self.parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
                      f'<title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>',
                      '<style>text{font-family:Segoe UI,Arial,sans-serif}.mono{font-family:Consolas,Menlo,monospace}</style>']
        self.rect(0, 0, width, height, self.p["bg"])

    def text(self, x, y, value, size=16, color="fg", weight=400, anchor="start", mono=False):
        color = self.p.get(color, color)
        cls = ' class="mono"' if mono else ''
        self.parts.append(f'<text x="{x:g}" y="{y:g}" fill="{color}" font-size="{size:g}" font-weight="{weight}" text-anchor="{anchor}"{cls}>{escape(str(value))}</text>')

    def rect(self, x, y, w, h, color, **attrs):
        extra = ' '.join(f'{k.replace("_", "-")}="{escape(str(v))}"' for k, v in attrs.items())
        self.parts.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" fill="{self.p.get(color, color)}" {extra}/>')

    def line(self, x1, y1, x2, y2, color="rule", width=1, dash=None):
        dashed = f' stroke-dasharray="{dash}"' if dash else ''
        self.parts.append(f'<line x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" stroke="{self.p.get(color, color)}" stroke-width="{width:g}"{dashed}/>')

    def save(self, path):
        path.write_text('\n'.join(self.parts + ['</svg>']) + '\n', encoding="utf-8")


def compact(value):
    sign = "−" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000:
        return f"{sign}{value / 1_000_000:.1f}m"
    if value >= 1000:
        return f"{sign}{value / 1000:.1f}k"
    return f"{sign}{value:g}"


def date_label(value):
    return datetime.fromisoformat(value[:10]).strftime("%d %b")


def render_activity(data, theme, mobile=False):
    w, h = (480, 618) if mobile else (960, 574)
    s = SVG(w, h, theme, "Code exchange — weekly commit candles", "Actual additions and deletions from authored, non-merge commits in selected public default branches. Candles represent cumulative net changed lines within the reporting window; volume is commits. Not a measure of code quality.")
    p, right = (24, w - 24) if mobile else (32, w - 32)
    totals, weeks = data["totals"], data["weeks"]
    s.text(p, 39, "Code exchange", 24, weight=600)
    s.text(right, 38, "$ECON", 17, "gold", anchor="end", mono=True)
    subtitle = f"{data['window']['days']} days · weekly candles · public code"
    s.text(p, 67, subtitle, 15, "muted")
    s.line(p, 86, right, 86)
    columns = [p, p + (w - p * 2) / 3, p + 2 * (w - p * 2) / 3]
    for x, title, val, color in zip(columns, ["Lines added", "Lines removed", "Commits"], [totals["additions"], totals["deletions"], totals["commits"]], ["up", "down", "fg"]):
        s.text(x, 113, title, 14 if mobile else 15, "muted")
        prefix = "+" if color == "up" else "−" if color == "down" else ""
        s.text(x, 151, prefix + compact(val), 27 if mobile else 34, color, 500, mono=True)
    s.text(p, 186, "Cumulative net changed lines", 14, "muted")
    x0, x1, y0, y1 = p + 2, right - 59, 211, 416 if mobile else 389
    values = [0] + [bar[key] for bar in weeks for key in ("low", "high")]
    minimum, maximum = min(values), max(values)
    rough_step = max(maximum - minimum, 10) / 4
    power = 10 ** math.floor(math.log10(rough_step))
    tick_step = next(n * power for n in (1, 2, 2.5, 5, 10) if n * power >= rough_step)
    lo = math.floor(minimum / tick_step) * tick_step
    hi = math.ceil(maximum / tick_step) * tick_step
    if hi == lo:
        hi = lo + 4 * tick_step
    scale = lambda val: y1 - (val - lo) / (hi - lo) * (y1 - y0)
    for i in range(round((hi - lo) / tick_step) + 1):
        val = lo + tick_step * i
        y = scale(val)
        s.line(x0, y, right - 52, y)
        s.text(right, y + 5, compact(round(val)), 12, "muted", anchor="end", mono=True)
    if lo <= 0 <= hi:
        s.line(x0, scale(0), right - 52, scale(0), "muted", dash="3 6")
    step = (x1 - x0) / max(len(weeks), 1)
    volume_y, volume_h = y1 + 36, 46
    max_commits = max([bar["commits"] for bar in weeks] + [1])
    for i, bar in enumerate(weeks):
        x = x0 + (i + .5) * step
        color = "up" if bar["close"] > bar["open"] else "down" if bar["close"] < bar["open"] else "muted"
        body_w = min(24, step * .47)
        s.parts.append(f'<g><title>{escape(bar["start"])}: {bar["commits"]} commits, +{bar["additions"]:,} / −{bar["deletions"]:,} lines; net {bar["close"] - bar["open"]:+,}</title>')
        if bar["commits"]:
            s.line(x, scale(bar["high"]), x, scale(bar["low"]), color, 1.7)
            body_top = min(scale(bar["open"]), scale(bar["close"]))
            body_h = abs(scale(bar["open"]) - scale(bar["close"]))
            s.rect(x - body_w / 2, body_top - (1 if body_h < 2 else 0), body_w, max(2, body_h), color)
        else:
            s.line(x - body_w / 2, scale(bar["open"]), x + body_w / 2, scale(bar["open"]), "muted", 1.2)
        v = bar["commits"] / max_commits * volume_h
        if v:
            s.rect(x - body_w / 2, volume_y + volume_h - v, body_w, max(2, v), color, opacity="0.58")
        s.parts.append('</g>')
        if i % (4 if mobile else 2) == 0 or (i == len(weeks) - 1 and i % (4 if mobile else 2) != 1):
            s.text(x, volume_y + volume_h + 21, date_label(bar["start"]), 11 if mobile else 12, "muted", anchor="middle", mono=True)
    s.text(right, volume_y + 17, "Vol.", 12, "muted", anchor="end")
    s.text(right, volume_y + 36, str(max_commits), 12, "muted", anchor="end", mono=True)
    if not totals["commits"]:
        s.text((x0 + x1) / 2, (y0 + y1) / 2, "No authored commits in this window", 15, "muted", anchor="middle")
    foot = h - (59 if mobile else 54)
    s.line(p, foot - 17, right, foot - 17)
    scope = f"{data['coverage']['repository_count']} repositories · default branches"
    s.text(p, foot + 3, scope, 13, "muted")
    updated = data["generated_at"][:10]
    if mobile:
        s.text(p, foot + 27, f"Snapshot {updated} · UTC", 13, "muted")
    else:
        s.text(right, foot + 3, f"Snapshot {updated} · UTC", 13, "muted", anchor="end")
        s.text(p, foot + 27, "Up = net additions. Down = net deletions. Refactoring counts, too.", 13, "muted")
    return s


def render_project(project, theme, mobile=False):
    slug, ticker, name, tagline, description, stack, category = project
    w, h = (480, 198) if mobile else (960, 154)
    s = SVG(w, h, theme, name, f"{description} {stack}. {category}.")
    s.rect(0, 0, 4, h, "gold" if slug in ("entryx", "whatnets") else "up")
    if mobile:
        s.text(24, 31, ticker, 15, "gold", 600, mono=True)
        s.text(456, 31, category, 13, "muted", anchor="end")
        s.text(24, 65, name, 25, weight=600)
        s.text(24, 96, tagline, 18)
        # Deliberate, stable line breaks keep every project readable at phone width.
        descriptions = {
            "dgx": ["Web chat, API access and a gateway", "for local inference."],
            "needle": ["Point at a product; an AI shopping", "assistant finds matches."],
            "entryx": ["NFT ticketing and RLUSD payments", "on XRPL Testnet."],
            "whatnets": ["A WhatsApp-style prototype with", "NETS QR payment flows."],
        }
        for i, line in enumerate(descriptions[slug]):
            s.text(24, 123 + i * 21, line, 16, "muted")
        s.text(24, 178, stack, 13, "muted")
    else:
        s.text(29, 43, ticker, 21, "gold", 600, mono=True)
        s.line(103, 24, 103, 130)
        s.text(128, 43, name, 24, weight=600)
        s.text(928, 42, category, 14, "muted", anchor="end")
        s.text(128, 73, tagline, 19)
        s.text(128, 100, description, 16, "muted")
        s.text(128, 130, stack, 14, "muted", mono=True)
    return s


def render_open_source(data, theme, mobile=False):
    source = data["open_source"]
    w, h = (480, 382) if mobile else (960, 286)
    s = SVG(w, h, theme, "Open source, compounded", f"{source['total_merged_prs']} merged public pull requests across {source['repository_count']} repositories outside the personal namespace. Snapshot {data['generated_at'][:10]}.")
    s.text(24 if mobile else 32, 39, "Open source, compounded", 24, weight=600)
    rows = sorted(source["repositories"], key=lambda item: (-item["merged_prs"], item["name"]))[:4]
    if mobile:
        s.text(24, 96, str(source["total_merged_prs"]), 46, "up", 500, mono=True)
        s.text(112, 76, "merged pull requests", 17)
        s.text(112, 100, f"across {source['repository_count']} repositories", 15, "muted")
        s.line(24, 124, 456, 124)
        for i, row in enumerate(rows):
            y = 158 + i * 40
            s.text(24, y, row["name"], 15, "fg", mono=True)
            s.text(456, y, str(row["merged_prs"]), 16, "up", anchor="end", mono=True)
        s.text(24, 340, "Public PRs outside my own namespace", 14, "muted")
        s.text(24, 364, f"All-time snapshot · {data['generated_at'][:10]}", 13, "muted")
    else:
        s.text(32, 126, str(source["total_merged_prs"]), 62, "up", 500, mono=True)
        s.text(32, 157, "merged pull requests", 18)
        s.text(32, 184, f"across {source['repository_count']} repositories", 16, "muted")
        s.line(320, 72, 320, 207)
        for i, row in enumerate(rows):
            y = 89 + i * 37
            s.text(352, y, row["name"], 17, mono=True)
            s.text(928, y, str(row["merged_prs"]), 18, "up", anchor="end", mono=True)
            if i < len(rows) - 1:
                s.line(352, y + 13, 928, y + 13)
        s.line(32, 230, 928, 230)
        s.text(32, 259, "Public PRs outside my own namespace", 14, "muted")
        s.text(928, 259, f"All-time snapshot · {data['generated_at'][:10]}", 13, "muted", anchor="end")
    return s


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/activity.json")
    parser.add_argument("--output", type=Path, default=ROOT / "assets")
    args = parser.parse_args()
    data = json.loads(args.data.read_text(encoding="utf-8"))
    if not data["coverage"]["complete"]:
        raise ValueError("Refusing to render an incomplete activity snapshot")
    args.output.mkdir(parents=True, exist_ok=True)
    for theme in PALETTES:
        for mobile in (False, True):
            suffix = f"{theme}{'-mobile' if mobile else ''}"
            render_activity(data, theme, mobile).save(args.output / f"activity-{suffix}.svg")
            render_open_source(data, theme, mobile).save(args.output / f"open-source-{suffix}.svg")
            for project in PROJECTS:
                render_project(project, theme, mobile).save(args.output / f"project-{project[0]}-{suffix}.svg")
    print("Rendered activity, contribution and project boards in light/dark and mobile layouts.")


if __name__ == "__main__":
    main()
