"""Assembles README.md and the range pages, and checks profile.json before rendering."""
from __future__ import annotations

from datetime import date
from html import escape
import re

from .svg import LOGOS, ROOT, THEMES
from .market import DEFAULT_VIEW, Market, VIEWS, View
from .widgets import (HEADER_LEFT_PCT, HEADER_STAT_PCT, HEADER_STATS, INDEX_TILES, legend_pct, RANGE_PCT, TAB_PCT,
                      header_change, header_stat, header_title, index_tile, legend_item, legend_items, range_label, tab, tape)
from .chart import AXIS_PCT, Geometry, candle_title, chart_axis, chart_dates, chart_slice, explain
from .lists import achievement_tile, collaboration_row, language_row, project_row, section_header, stack_tile


OWNER = "Haoming9527"


LIVE_BASE = f"https://raw.githubusercontent.com/{OWNER}/{OWNER}/market/"


BANNER_LIVE = f"https://raw.githubusercontent.com/{OWNER}/{OWNER}/main/"


BANNERS = ROOT / "assets/banners"


DEFAULT_BANNER = {"file": "nyse-banner.png", "alt": "The New York Stock Exchange facade at dusk"}


PROFILE_URL = f"https://github.com/{OWNER}"


VIEW_URL = f"https://github.com/{OWNER}/{OWNER}/blob/market/views/{{}}.md"


VISIBLE_LANGUAGES = 6


VISIBLE_TOOLS = 8


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
    details = config.get("banner", DEFAULT_BANNER)
    banner_img = f'<img src="{escape(banner + "assets/banners/" + details["file"])}" width="100%" alt="{escape(details.get("alt", ""))}">'
    stat = lambda key, label: r.picture(f"{p}-lh-{key}", label, f"{HEADER_STAT_PCT}%", explain(view, key))
    header = (r.picture(f"{p}-lh-title", "Lines index", f"{HEADER_LEFT_PCT}%", explain(view, "price"))
              + "".join(stat(key, label) for key, label in HEADER_STATS[:3]) + "<br>"
              + r.picture(f"{p}-lh-change", "Change", f"{HEADER_LEFT_PCT}%", explain(view, "change"))
              + "".join(stat(key, label) for key, label in HEADER_STATS[3:]) + "<br>"
              + "".join(r.picture(f"{p}-lh-{key.lower()}", key, f"{legend_pct(view, key)}%", explain(view, key))
                        for key in legend_items(view)))
    return "\n\n".join(filter(None, [
        "<!-- Generated by scripts/render_profile.py. Edit profile.json or the script, not this file. -->",
        f'<p>{banner_img}<br>{r.picture(f"{p}-tape", "Live tape", "100%")}</p>',
        f'<p>{tabs}{r.picture(f"{p}-range", f"{view.name} view", f"{RANGE_PCT}%", explain(view, "range"))}</p>',
        f"<p>{tiles}</p>",
        f'<p>{header}<br>{slices}'
        f'{r.picture(f"{p}-chart-axis", "Price axis", f"{AXIS_PCT}%", explain(view, "axis"))}'
        f'<br>{r.picture(f"{p}-chart-dates", "Dates", "100%", explain(view, "dates"))}</p>',
        f'<p>{r.link(f"https://github.com/{username}?tab=repositories", r.picture(f"{p}-section-watchlist", "Watchlist", "100%", explain(view, "watchlist")))}'
        f"<br>{rows(projects)}</p>",
        f'<p>{r.picture(f"{p}-section-languages", "Languages", "100%", explain(view, "languages"))}<br>{rows(languages[:VISIBLE_LANGUAGES])}</p>',
        more(len(languages), "languages", rows(languages[VISIBLE_LANGUAGES:])) if len(languages) > VISIBLE_LANGUAGES else "",
        f'<p>{r.picture(f"{p}-section-stack", "Tech stack", "100%", explain(view, "stack"))}<br>{pairs(stack[:VISIBLE_TOOLS])}</p>',
        more(len(stack), "tools", pairs(stack[VISIBLE_TOOLS:])) if len(stack) > VISIBLE_TOOLS else "",
        f'<p>{r.link(market.open_source["url"], r.picture(f"{p}-section-collabs", "Collaborations", "100%", explain(view, "collabs")))}'
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
        emit(f"{p}-range", lambda t, m, v=view: range_label(v, t, m))
        for key, *_ in INDEX_TILES:
            emit(f"{p}-index-{key}", lambda t, m, v=view, key=key: index_tile(v, key, t, m))
        emit(f"{p}-lh-title", lambda t, m, v=view: header_title(v, t, m))
        emit(f"{p}-lh-change", lambda t, m, v=view: header_change(v, t, m))
        for key, _ in HEADER_STATS:
            emit(f"{p}-lh-{key}", lambda t, m, v=view, key=key: header_stat(v, key, t, m))
        for key in legend_items(view):
            emit(f"{p}-lh-{key.lower()}", lambda t, m, v=view, key=key: legend_item(v, key, t, m))
        emit(f"{p}-chart-axis", lambda t, m, v=view: chart_axis(v, t, m))
        emit(f"{p}-chart-dates", lambda t, m, v=view: chart_dates(v, t, m))
        for i in range(len(view.candles)):
            emit(f"{p}-chart-{i:02d}", lambda t, m, v=view, i=i: chart_slice(v, i, t, m))
        label = view.label
        for key, title, columns in (("watchlist", "Watchlist", ("Project", "Net lines", label)),
                                    ("languages", "Languages", ("Language", "Share", label)),
                                    ("stack", "Tech stack", ()),
                                    ("collabs", "Collaborations", ("Repository", "Merged PRs", label))):
            emit(f"{p}-section-{key}", lambda t, m, title=title, columns=columns: section_header(title, columns, t, m))
        for i in range(len(config["projects"])):
            emit(f"{p}-project-{i}", lambda t, m, v=view, i=i: project_row(v, i, t, m))
        for i in range(len(market.languages)):
            emit(f"{p}-lang-{i}", lambda t, m, v=view, i=i: language_row(v, i, t, m))
        for i, tool in enumerate(market.tools):
            emit(f"{p}-stack-{i}", lambda t, m, v=view, tool=tool: stack_tile(v, tool, t, m))
        for i in range(len(config["collaborations"])):
            emit(f"{p}-collab-{i}", lambda t, m, v=view, i=i: collaboration_row(v, i, t, m))
        pages[code] = render_page(view, base, "" if code == DEFAULT_VIEW else BANNER_LIVE)
    readme = pages.pop(DEFAULT_VIEW)
    return files, readme, pages, market.missing_logos()


LOGO_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.(svg|png|jpe?g)", re.I)


def check_config(config: dict) -> None:
    """profile.json can be edited from the dashboard, so refuse logos outside assets/logos and non-https links."""
    files = [entry.get("logo") for entry in config.get("achievements", [])]
    for entry in config.get("projects", []) + config.get("collaborations", []):
        files += list(entry["wordmark"].values()) if "wordmark" in entry else [entry.get("logo")]
    for name in files:
        if not isinstance(name, str) or not LOGO_NAME.fullmatch(name) or not (LOGOS / name).is_file():
            raise ValueError(f"profile.json names a missing or unsafe logo: {name!r}")
    banner = config.get("banner", DEFAULT_BANNER)
    name = banner.get("file") if isinstance(banner, dict) else None
    if not isinstance(name, str) or not LOGO_NAME.fullmatch(name) or not (BANNERS / name).is_file() \
            or not isinstance(banner.get("alt", ""), str):
        raise ValueError(f"profile.json names a missing or unsafe banner: {name!r}")
    for url in [config.get("portfolio", "")] + [entry.get("url", "") for entry in config.get("achievements", [])]:
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ValueError(f"profile.json links must use https: {url!r}")
