"""Everything derived from the snapshot: candles, daily series and the D/W/M/Q/Y views."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import cached_property

import catalog


MA_PERIODS = (5, 10)   # moving averages drawn once a view has at least MA_MINIMUM candles


MA_MINIMUM = 12


PERIOD_NOUNS = {"D": "day", "W": "week", "M": "month", "Q": "quarter", "Y": "year"}


# code: (name, days behind every change figure, change label)
VIEWS = {"D": ("Daily", 1, "1D"), "W": ("Weekly", 7, "7D"), "M": ("Monthly", 30, "1M"),
         "Q": ("Quarterly", 91, "3M"), "Y": ("Yearly", 365, "1Y")}


DEFAULT_VIEW = "W"


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
            for repo in self.open_source["repositories"] + self.open_source.get("owned_repositories", []):
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
        since = self.market.today - timedelta(days=self.days)
        return sum(row["additions"] - row["deletions"] for row in self.market.commits if row["day"] > since)

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

    def index(self, key: str) -> dict:
        events = self.market.events(key)
        base = self.market.undated_stars() if key == "stars" else 0
        value = base + sum(events.values())
        delta = self.change(events)
        return {"series": self.series(events, base), "value": value, "delta": delta, "previous": value - delta}
