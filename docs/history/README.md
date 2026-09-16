# docs/history

- `CHANGELOG-TIMELINE.md` — complete chronological history of the agent (21 Aug → 15 Sep 2026), every version line, feature, command, integration and fix.
- `evolution-infographic.svg` / `.png` — visual progress infographic (KPIs, daily growth chart, milestone timeline, capability stack).
- Regenerate the SVG: `python3 scripts/build_history_infographic.py` (no dependencies). PNG rendered with `@resvg/resvg-js`.

Daily metrics in the chart were measured with `git ls-tree` at the last commit on `main` for each day
(engine modules, connectors, test files, prompt packs, docs) plus commit counts per day.
