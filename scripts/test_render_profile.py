"""Checks for the market-board renderer: every page is complete, and the stock-app maths is right."""

from datetime import date, timedelta
import re
import unittest

import render_profile as render


NOW = "2026-10-30T04:00:00Z"   # 12:00 on 30 Oct in Singapore, the configured timezone
CONFIG = {
    "github_username": "Haoming9527", "display_name": "Economist", "role": "R&D AI Engineer",
    "portfolio": "https://example.com/", "utc_offset_hours": 8, "timezone_label": "SGT",
    "projects": [{"repository": "Haoming9527/app", "name": "App", "ticker": "APP", "logo": "needle.png"}],
    "collaborations": [{"repository": "other/project", "name": "Project", "logo": "dsh-ops.png"}],
    "achievements": [{"rank": "Winner", "event": "Event", "tag": "App", "logo": "div0.png", "url": "https://example.com/"}],
}


def commit(day: str, additions: int, deletions: int, sha: str, repository: str = "Haoming9527/app") -> dict:
    return {"sha": sha * 40, "repository": repository, "timestamp": f"{day}T02:00:00Z", "additions": additions,
            "deletions": deletions, "languages": {"TypeScript": [additions, deletions]}, "url": "https://example.com/"}


def snapshot(commits: list[dict]) -> dict:
    return {
        "schema_version": 3, "github_username": "Haoming9527", "generated_at": NOW,
        "window": {"start": "2026-08-01T00:00:00Z", "end": NOW, "days": 90, "timezone": "UTC"},
        "coverage": {"complete": True}, "commits": commits, "logos": {},
        "open_source": {"url": "https://github.com/search?q=x", "repositories": [
            {"name": "other/project", "merged_prs": 2, "url": "https://github.com/other/project", "language": "TypeScript",
             "stars": 9, "merged_at": ["2026-09-01T00:00:00Z", "2026-10-29T00:00:00Z"]}]},
        "languages": {"bytes": {"TypeScript": 300, "CSS": 100}},
        "stack": {"React": ["Haoming9527/app"]},
        "stars": {"total": 9, "repositories": [{"name": "other/project", "stars": 9, "starred_on": {"2026-10-01": 9}}]},
    }


HISTORY = [commit("2026-10-20", 100, 10, "a"), commit("2026-10-25", 50, 80, "b"), commit("2026-10-29", 20, 5, "c")]


class PageTests(unittest.TestCase):
    def test_every_page_only_references_generated_widgets(self):
        files, readme, pages, missing = render.build(snapshot(HISTORY), CONFIG, "BASE/")
        self.assertEqual(sorted(pages), ["D", "M", "Q", "Y"])
        self.assertEqual(missing, [])
        for page in [readme, *pages.values()]:
            names = set(re.findall(r"BASE/assets/gen/([a-z0-9-]+)-light\.svg", page))
            self.assertTrue(names)
            for name in names:
                for variant in ("light", "dark", "light-m", "dark-m"):
                    self.assertIn(f"{name}-{variant}.svg", files)
        self.assertIn("tab-w-on", readme)
        self.assertIn("w-status", readme)

    def test_tabs_and_status_share_one_row(self):
        self.assertLessEqual(len(render.VIEWS) * render.TAB_PCT + render.STATUS_PCT, 100)

    def test_an_empty_history_still_renders(self):
        files, readme, pages, _ = render.build(snapshot([]), CONFIG, "BASE/")
        self.assertIn("w-lines-header", readme)
        self.assertTrue(all(name.endswith(".svg") for name in files))


class MarketMathsTests(unittest.TestCase):
    def view(self, code: str, commits=HISTORY) -> render.View:
        return render.View(render.Market(snapshot([dict(row) for row in commits]), CONFIG), code)

    def test_range_stats_follow_the_additions_first_rule(self):
        stats = self.view("W").range_stats
        self.assertEqual(stats, {"open": 90, "high": 140, "low": 60, "close": 75, "vol": 2, "added": 70, "deleted": 85})
        self.assertEqual(self.view("W").lines_change, -15)

    def test_moving_averages_need_enough_candles(self):
        weekly = self.view("W")
        ma5, ma10 = weekly.moving_averages
        closes = [candle["close"] for candle in weekly.candles]
        self.assertEqual(len(ma5), len(closes))
        self.assertIsNone(ma5[3])
        self.assertAlmostEqual(ma5[-1], sum(closes[-5:]) / 5)
        self.assertAlmostEqual(ma10[-1], sum(closes[-10:]) / 10)
        self.assertEqual(self.view("Y").moving_averages, [])

    def test_last_commit_age_is_rounded_to_hours_and_days(self):
        self.assertEqual(render.ago(timedelta(minutes=12)), "<1h ago")
        self.assertEqual(render.ago(timedelta(hours=5, minutes=59)), "5h ago")
        self.assertEqual(render.ago(timedelta(days=3, hours=4)), "3d ago")

    def test_percentage_badges_and_new_listings(self):
        since = date(2026, 10, 23)
        self.assertEqual(render.change_badge(50, 0, date(2026, 10, 29), since), ("NEW", "new"))
        self.assertEqual(render.change_badge(10, 100, date(2026, 1, 1), since), ("+10.00%", None))
        self.assertEqual(render.change_badge(-5, 200, date(2026, 1, 1), since), ("\u22122.50%", None))
        self.assertEqual(render.change_badge(0, 0, None, since), ("0.00%", None))

    def test_view_badge_uses_the_value_at_the_start_of_the_range(self):
        weekly = self.view("W")
        lines = weekly.market.events("repo-lines", "Haoming9527/app")
        self.assertEqual(weekly.badge(lines), (-15, "\u221216.67%", None))
        newcomer = self.view("W", [commit("2026-10-28", 30, 0, "d")])
        self.assertEqual(newcomer.badge(newcomer.market.events("repo-lines", "Haoming9527/app")), (30, "NEW", "new"))


if __name__ == "__main__":
    unittest.main()
