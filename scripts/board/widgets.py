"""The tape, the D/W/M/Q/Y tabs, the index tiles and the Lines index header."""
from __future__ import annotations

from datetime import timedelta

from .formatting import MINUS, compact, num, percent, signed, text_width, tone
from .svg import SVG
from .market import MA_PERIODS, VIEWS, View


def tape(view: View, theme: str, mobile: bool) -> SVG:
    market = view.market
    w, h, size = (400, 46, 17) if mobile else (846, 40, 14)
    items = [(market.config["role"].upper(), "", "", "none")]
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


# The Lines index header is a row of separate images so each part gets its own hover text:
#   row 1: title and price | Open | High | Low
#   row 2: range change    | Vol  | Added | Deleted   (with the divider along the bottom)
#   row 3: O H L C MA5 MA10 legend items
# Widths are shares of the full header, identical on desktop and phone.
HEADER_W = {False: 846, True: 400}
HEADER_LEFT_PCT, HEADER_STAT_PCT = 55.0, 14.9
HEADER_STATS = (("open", "Open"), ("high", "High"), ("low", "Low"), ("vol", "Vol"), ("added", "Added"), ("deleted", "Deleted"))
ROW_H = {False: (70, 40, 32), True: (66, 48, 40)}


def _legend_value(view: View, key: str) -> str:
    if key.startswith("MA"):
        return compact(view.moving_averages[MA_PERIODS.index(int(key[2:]))][-1])
    return compact(view.candles[-1][{"O": "open", "H": "high", "L": "low", "C": "close"}[key]])


def legend_pct(view: View, key: str) -> float:
    """Just wide enough for the item (desktop: label and value side by side; phone: stacked)."""
    value, first = _legend_value(view, key), key == "O"
    desktop = (24 if first else 4) + text_width(key, 14, 500) + 6 + text_width(value, 14, 600) + 16
    phone = (14 if first else 4) + max(text_width(key, 11, 500), text_width(value, 11, 600)) + 7
    return round(max(desktop / HEADER_W[False], phone / HEADER_W[True]) * 100, 2)


def _piece(view: View, pct: float, row: int, theme: str, mobile: bool, label: str) -> SVG:
    return SVG(HEADER_W[mobile] * pct / 100, ROW_H[mobile][row], theme, label, TICK_CSS)


def header_title(view: View, theme: str, mobile: bool) -> SVG:
    s = _piece(view, HEADER_LEFT_PCT, 0, theme, mobile, "Lines index")
    pad, size = (14, 15) if mobile else (24, 18)
    s.text(pad, 22 if mobile else 26, "Lines index", size, "fg", 600)
    s.text(pad + text_width("Lines index", size, 600) + 8, 22 if mobile else 26, f"since {view.market.first:%b %Y}",
           11 if mobile else 13, "muted", 500)
    price, price_size, price_y = num(view.market.lines), (28 if mobile else 32), (56 if mobile else 64)
    flash(s, pad, price_y, text_width(price, price_size, 700), price_size, tone(view.lines_change))
    s.text(pad, price_y, price, price_size, "fg", 700)
    return s


def header_change(view: View, theme: str, mobile: bool) -> SVG:
    s = _piece(view, HEADER_LEFT_PCT, 1, theme, mobile, "Change")
    change = view.lines_change
    text = f"{signed(change)} {percent(change, view.range_stats['open'])} {view.label}".replace("  ", " ")
    s.text(14 if mobile else 24, 24 if mobile else 22, text, 13 if mobile else 16, tone(change), 600 if mobile else 500)
    s.line(0, s.h - 1, s.w, s.h - 1, "faint")
    return s


def header_stat(view: View, key: str, theme: str, mobile: bool) -> SVG:
    label = dict(HEADER_STATS)[key]
    row = [k for k, _ in HEADER_STATS].index(key) // 3
    s = _piece(view, HEADER_STAT_PCT, row, theme, mobile, label)
    stats = view.range_stats
    value = (f"{stats['vol']:,}" if key == "vol" else f"+{compact(stats['added'])}" if key == "added"
             else (f"{MINUS}{compact(stats['deleted'])}" if stats["deleted"] else "0") if key == "deleted"
             else compact(stats[key]))
    if mobile:   # label above value: a phone cell is narrow
        y = (34, 52) if row == 0 else (18, 36)
        s.text(4, y[0], label, 11, "muted", 500)
        s.text(4, y[1], value, 13, "fg", 600)
    else:
        y = 60 if row == 0 else 22
        s.text(8, y, label, 12, "muted", 500)
        s.text(s.w - 14, y, value, 14, "fg", 600, "end")
    if row == 1:
        s.line(0, s.h - 1, s.w, s.h - 1, "faint")
    return s


def legend_items(view: View) -> list[str]:
    """O H L C, plus each moving average that has a value on this view."""
    averages = [f"MA{k}" for k, values in zip(MA_PERIODS, view.moving_averages) if values and values[-1] is not None]
    return ["O", "H", "L", "C", *averages]


def legend_item(view: View, key: str, theme: str, mobile: bool) -> SVG:
    s = _piece(view, legend_pct(view, key), 2, theme, mobile, key)
    value = _legend_value(view, key)
    if key.startswith("MA"):
        color = label_color = s.p["ma"][MA_PERIODS.index(int(key[2:]))]
    else:
        color, label_color = "fg", "muted"
    x = (14 if mobile else 24) if key == "O" else 4
    if mobile:
        s.text(x, 16, key, 11, label_color, 500)
        s.text(x, 32, value, 11, color, 600)
    else:
        s.text(x, 22, key, 14, label_color, 500)
        s.text(x + text_width(key, 14, 500) + 6, 22, value, 14, color, 600)
    return s
