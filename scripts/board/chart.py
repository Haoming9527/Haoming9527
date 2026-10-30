"""The candle chart: per-candle slices, the price axis, the date strip and hover explanations."""
from __future__ import annotations

import math

from .formatting import MINUS, compact, num, signed, text_width, tone
from .svg import SVG
from .market import PERIOD_NOUNS, View, period_label


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
        if not candle["commits"]:
            return f"{label} so far (updates live): no commits yet"
        change = candle["close"] - candle["open"]
        why = ("red because more lines were deleted than added so far" if change < 0
               else "green because more lines were added than deleted so far")
        return (f"{label} so far (updates live): {candle['commits']} commit{'s' if candle['commits'] != 1 else ''}, "
                f"+{candle['additions']:,} / {MINUS}{candle['deletions']:,} lines ({signed(change)}); {why}")
    if not candle["commits"]:
        return f"{label}: no commits; index {num(candle['close'])}"
    return (f"{label}: {candle['commits']} commit{'s' if candle['commits'] != 1 else ''}, "
            f"+{candle['additions']:,} / {MINUS}{candle['deletions']:,} lines; open {num(candle['open'])}, "
            f"high {num(candle['high'])}, low {num(candle['low'])}, close {num(candle['close'])}")


def chart_slice(view: View, index: int, theme: str, mobile: bool) -> SVG:
    candles = view.candles
    g = Geometry(candles, mobile)
    candle, w = candles[index], g.slice_w
    delay = index * min(.07, .9 / g.n)
    css = ('.rise{transform-box:fill-box;transform-origin:50% 100%;animation:rise .7s cubic-bezier(.2,.8,.2,1) both;'
           f'animation-delay:{delay:.2f}s}}@keyframes rise{{from{{transform:scaleY(0);opacity:0}}}}')
    s = SVG(w, g.h, theme, candle_title(view.code, candle), css)
    for tick in g.ticks():
        s.line(0, g.y(tick), w, g.y(tick), "grid")
    s.line(0, g.vol_bottom + .5, w, g.vol_bottom + .5, "grid")
    last = candles[-1]
    s.line(0, g.y(last["close"]), w, g.y(last["close"]), tone(view.lines_change), 1.2, stroke_dasharray="4 3", opacity=".8")
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
    labels = [period_label(view.code, candle["start"]) for candle in candles]
    widest = max(text_width(label, size, 500) for label in labels) + (10 if mobile else 14)
    step = max(1, math.ceil(widest / g.slice_w))
    for i in range(g.n - 1, -1, -step):
        x = (i + .5) * g.slice_w
        if x - text_width(labels[i], size, 500) / 2 >= 0:
            s.text(x, h - 9, labels[i], size, "muted", 500, "middle")
    return s


def explain(view: View, what: str) -> str:
    """Hover text for the chart and column legends."""
    noun = PERIOD_NOUNS[view.code]
    window = f"{view.days} day{'s' if view.days != 1 else ''}"
    return {
        "header": f"Lines index: lines added minus lines deleted across my public repositories. "
                  f"Open, High, Low: the index {window} ago and its extremes since; Vol: commits; Added/Deleted: lines in that time. "
                  f"O H L C: the latest {noun}'s candle. " +
                  (f"MA5 / MA10: average close of the last 5 / 10 {noun}s, drawn as the gold and purple lines. "
                   if view.moving_averages else "") +
                  "Green candles added more lines than they deleted, red ones deleted more.",
        "range": f"Every change on this page compares with {window} ago.",
        "axis": f"The tag and dashed line show the index now, coloured by the {view.label} change. "
                f"VOL is the most commits in any one {noun}.",
        "dates": f"Each label marks the start of a {noun}.",
        "watchlist": f"Net lines: lines added minus deleted in each project, all time. {view.label}: the change over the last {window}.",
        "languages": f"Share: the language's share of the code in my repositories (GitHub Linguist). "
                     f"{view.label}: net lines written in it over the last {window}.",
        "stack": "Tools detected from each repository's manifests. The number is commits in the repositories that use it.",
        "collabs": f"Merged PRs: my pull requests merged into each project. {view.label}: merged in the last {window}.",
    }[what] if not what.startswith("ma") else (
        f"MA{what[2:]}: the average close of the last {what[2:]} {noun}s. It smooths the candles so the trend is easier to see.")
