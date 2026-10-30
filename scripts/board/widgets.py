"""The tape, the D/W/M/Q/Y tabs, the index tiles and the Lines index header."""
from __future__ import annotations

from datetime import timedelta

from .formatting import MINUS, compact, num, percent, signed, text_width, tone
from .svg import SVG
from .market import MA_PERIODS, VIEWS, View


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


TAB_PCT, RANGE_PCT = 11.0, 44.6


def tab(code: str, active: bool, theme: str, mobile: bool) -> SVG:
    unit = 4.0 if mobile else 8.46
    w, h = TAB_PCT * unit, (40 if mobile else 44)
    s = SVG(w, h, theme, f"{VIEWS[code][0]} view")
    size = 17 if mobile else 15
    if active:
        s.rect(3, 4, w - 6, h - 8, "pill", (h - 8) / 2)
    s.text(w / 2, h / 2 + size * .36, code, size, "fg" if active else "muted", 700 if active else 600, "middle")
    return s


def range_label(view: View, theme: str, mobile: bool) -> SVG:
    unit = 4.0 if mobile else 8.46
    w, h = RANGE_PCT * unit, (40 if mobile else 44)
    s = SVG(w, h, theme, f"{view.name} view; changes over {view.label}")
    size = 15 if mobile else 13
    note = view.label if mobile else f"{view.label} change"
    s.text(w - 4, h / 2 + size * .36, note, size, "muted", 500, "end")
    s.text(w - 4 - text_width(note, size, 500) - 10, h / 2 + size * .36, view.name, size, "fg", 600, "end")
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
