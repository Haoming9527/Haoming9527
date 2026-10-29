# The code exchange

The profile uses repository-hosted images and ordinary Markdown. No external stats-card service, browser script, API key in an image URL, or separate deployment is needed.

## What the candles mean

The collector reads the explicit public repository list in `profile.json`. It retrieves commits authored by `Haoming9527` on each repository's default branch over the last 90 UTC calendar dates, through the snapshot time. Git committer timestamps determine ordering. UTC weeks begin on Monday; the first and last week can be partial.

The running index starts at **zero**, not a simulated share price. For each commit:

1. Add its added lines to the index.
2. Record the resulting high if it exceeds the week's previous high.
3. Subtract its deleted lines.
4. Record the resulting low if it falls below the week's previous low.

The weekly open is the previous week's close; the close is the cumulative net changed lines at the end of that week. Wicks include the starting value and every constructed excursion. Additions-first is a consistent drawing convention, not an observed sequence of edits within the commit. Green means net additions; red means net deletions. The lower histogram shows commit counts. Flat marks represent weeks without commits.

All files reported by GitHub's commit statistics are included, including lockfiles and generated files. Large imports can dominate the scale. Binary changes may have zero line statistics. The index is **net changed lines in this window**, not the total size of the codebase, a measure of skill, or financial performance.

Merge commits are excluded to avoid counting merged diffs twice. Identical SHAs across selected repositories count once. Other authors, private repositories, non-default branches, and this profile repository are excluded. Excluding the profile prevents its scheduled refresh commits from inflating the chart. Public repositories must be added to the configuration explicitly, so the scope remains inspectable.

## Merged contributions

The second board uses GitHub's issue search with `is:pr author:Haoming9527 is:merged -user:Haoming9527 is:public`. It counts all-time merged public pull requests outside the personal namespace. Those repositories can include collaborative projects; this metric is not a claim of independent authorship or a statement about every project's license. The board shows the four repositories with the largest counts, plus the total across all matching repositories.

The collector checks pagination, reported totals, and `incomplete_results`. If results exceed GitHub's 1,000-result search limit, it stops until the query is partitioned rather than publishing a truncated count. Recent PR entries in the JSON are ordered by last update time, not merge time.

## Refreshing

The workflow runs daily at **08:17 Singapore time**, on manual dispatch, and after changes to the collector, renderer, configuration or workflow on `main`. GitHub schedules can run later than the requested time.

```sh
python -m unittest discover -s scripts -p 'test_*.py' -v
python scripts/activity_data.py
python scripts/render_profile.py
```

Python 3.12 or newer is sufficient; there are no pip dependencies. Set `GITHUB_TOKEN` in the environment for local collection to avoid GitHub's small unauthenticated request allowance. Never commit the token. In Actions, the built-in repository token is used automatically.

The fetch/render job has read-only contents permission. A separate publish job writes only the completed JSON and SVG assets. Git uses Shen Haoming's configured identity. Collection failures preserve the last complete snapshot, and rendering or test failures prevent publication. The profile's images retain their snapshot dates so an interrupted refresh is visible.

Theme-specific `picture` sources choose light or dark assets. Dedicated mobile SVGs use larger type, simpler labels and a taller layout. The fallback images remain complete and readable when a client doesn't support theme selection. Source data and alt text keep the information accessible outside the visual boards.

## Editing the profile

- `README.md`: biography, links, stack and achievements.
- `profile.json`: GitHub identity and explicit activity coverage.
- `scripts/render_profile.py`: colors, project listing copy and SVG layouts.
- `assets/nyse-banner.png`: the final banner, adapted from the supplied photograph with no added lettering.
- `data/activity.json`: complete dated public snapshot, including per-commit audit links.
- `docs/sources.md`: evidence behind the biography, projects and track record.

To rerender the current data without network access, run only `python scripts/render_profile.py`. The collector also accepts `--now` for a reproducible cutoff and `--responses` for replaying saved API responses during troubleshooting.
