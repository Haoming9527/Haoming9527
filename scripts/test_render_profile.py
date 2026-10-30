"""Checks for the market-board renderer: every page is complete, and the chart maths is right."""

import base64
import json
import re
import unittest

import render_profile as render


NOW = "2026-10-30T04:00:00Z"   # 12:00 on 30 Oct in Singapore, the configured timezone
CONFIG = {
    "github_username": "Haoming9527", "display_name": "Economist", "role": "R&D AI Engineer",
    "portfolio": "https://example.com/", "utc_offset_hours": 8,
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
        self.assertIn("w-range", readme)

    def test_header_explains_its_stats_and_legend_on_hover(self):
        _, readme, pages, _ = render.build(snapshot(HISTORY), CONFIG, "BASE/")
        self.assertIn("MA5 / MA10: average close of the last 5 / 10 weeks", readme)
        self.assertIn("Open, High, Low: the index 7 days ago", readme)
        self.assertNotIn("MA5 / MA10", pages["Y"])   # too few yearly candles for an average

    def test_live_candle_says_why_it_is_red_or_green(self):
        def live_title(code, commits):
            view = render.View(render.Market(snapshot([dict(row) for row in commits]), CONFIG), code)
            return render.candle_title(code, view.candles[-1])
        self.assertIn("so far (updates live): no commits yet", live_title("D", HISTORY))
        down = [commit("2026-10-20", 100, 10, "a"), commit("2026-10-29", 36, 50, "c")]
        self.assertIn("+36 / \u221250 lines (\u221214); red because more lines were deleted than added", live_title("W", down))
        self.assertIn("(+15); green because more lines were added than deleted", live_title("W", HISTORY))

    def test_tabs_and_range_share_one_row(self):
        self.assertLessEqual(len(render.VIEWS) * render.TAB_PCT + render.RANGE_PCT, 100)

    def test_a_watchlist_project_can_be_shown_as_a_wordmark(self):
        config = json.loads(json.dumps(CONFIG))
        project = config["projects"][0]
        del project["logo"]
        project["wordmark"] = {"light": "intelidar-light.png", "dark": "intelidar-dark.png"}
        render.check_config(config)
        files, _, _, _ = render.build(snapshot(HISTORY), config, "BASE/")
        for theme in ("light", "dark"):
            mark = base64.b64encode((render.ROOT / "assets/logos" / f"intelidar-{theme}.png").read_bytes()).decode()
            with self.subTest(theme=theme):
                self.assertIn(mark, files[f"w-project-0-{theme}.svg"])

    def test_an_empty_history_still_renders(self):
        files, readme, pages, _ = render.build(snapshot([]), CONFIG, "BASE/")
        self.assertIn("w-lines-header", readme)
        self.assertTrue(all(name.endswith(".svg") for name in files))


class ConfigTests(unittest.TestCase):
    def test_unsafe_logo_or_link_is_refused(self):
        render.check_config(CONFIG)
        for change in ({"logo": "../README.md"}, {"logo": "missing.png"}, {"url": "javascript:alert(1)"}):
            config = json.loads(json.dumps(CONFIG))
            config["achievements"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                render.check_config(config)

    def test_a_missing_wordmark_is_refused(self):
        config = json.loads(json.dumps(CONFIG))
        config["projects"][0]["wordmark"] = {"light": "missing.png", "dark": "intelidar-dark.png"}
        with self.assertRaises(ValueError):
            render.check_config(config)


class MovingAverageTests(unittest.TestCase):
    def test_moving_averages_need_enough_candles(self):
        market = render.Market(snapshot([dict(row) for row in HISTORY]), CONFIG)
        weekly = render.View(market, "W")
        ma5, ma10 = weekly.moving_averages
        closes = [candle["close"] for candle in weekly.candles]
        self.assertEqual(len(ma5), len(closes))
        self.assertIsNone(ma5[3])
        self.assertAlmostEqual(ma5[-1], sum(closes[-5:]) / 5)
        self.assertAlmostEqual(ma10[-1], sum(closes[-10:]) / 10)
        self.assertEqual(render.View(market, "Y").moving_averages, [])


if __name__ == "__main__":
    unittest.main()
