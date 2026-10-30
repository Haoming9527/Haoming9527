"""List rows and tiles: watchlist, languages, tech stack, collaborations and track record."""
from __future__ import annotations


from .formatting import fit, kilo, num, signed, size_label, text_width, tone, wrap
from .svg import SVG
from .market import View


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


def list_row(theme: str, mobile: bool, *, logo: dict, name: str, sub: str, series: list, value: str,
             value_sub: str, change: float, change_label: str, label: str) -> SVG:
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
    s.text(L["value_x"], h / 2 + L["sub"] + 6, fit(value_sub, L["sub"] - 1, value_room), L["sub"] - 1, "muted", 400, "end")
    bx, bw = L["badge"]
    bh = 40 if mobile else 38
    s.badge(bx, h / 2 - bh / 2, bw, bh, change, change_label, L["badge_size"])
    s.line(L["pad"], h - .5, w - L["pad"], h - .5, "grid")
    return s


def project_row(view: View, i: int, theme: str, mobile: bool) -> SVG:
    project = view.market.config["projects"][i]
    events = view.market.events("repo-lines", project["repository"])
    commits = sum(1 for row in view.market.commits if row["repository"].lower() == project["repository"].lower())
    recent = view.change(events)
    logo = ({"wordmark": project["wordmark"]} if "wordmark" in project
            else {"file": project["logo"], "scale": .7, "fit": project.get("logo_fit", "cover")})
    return list_row(theme, mobile, logo=logo, name=project["name"], sub=project["ticker"], series=view.series(events),
                    value=num(sum(events.values())), value_sub=f"{commits:,} commits", change=recent,
                    change_label=signed(recent, True), label=f"{project['name']} repository")


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
    recent = view.change(events)
    logo = {"wordmark": entry["wordmark"]} if "wordmark" in entry else {"file": entry["logo"], "fit": "cover"}
    return list_row(theme, mobile, logo=logo, name=entry["name"], sub=source.get("language") or "Open source",
                    series=view.series(events), value=f"{int(sum(events.values())):,}",
                    value_sub=f"★ {kilo(market.stars_of(repository))}", change=recent, change_label=signed(recent),
                    label=f"{entry['name']} merged pull requests")


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
