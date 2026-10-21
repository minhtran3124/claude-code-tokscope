# Design prompt: the ink style for tokscope

A reusable prompt for designing a tokscope screen (dashboard page or the HTML report) in the "ink" style. It is adapted from the ink prompt of Claude Bot Local (claude-bot-projects `docs/design-prompt.md`), which follows [colorfigures](https://colorfigures.vercel.app/#washer). Fill in the two bracketed lines and paste the whole block.

- Kept from the source: paper, sheet, ink and rule colours, ink outlines, pill buttons, the flat navy shadow, mono labels, and the two bundled faces (tokscope already ships them in `tokscope/fonts/`).
- Changed on purpose: Claude Bot Local's swatches mean a project's state. tokscope has no states; its colours mean data. So the swatches are remapped to series and results below, and "no accent that isn't a state" becomes "no accent that isn't data".
- Changed on purpose: tokscope pages are dense tables and numbers. Shadows go on one card per page, not every card, and tables keep thin rules.
- Text colours were checked for WCAG AA on paper and sheet in both themes (contrast in brackets, worst of the two). Light-theme swatch fills are below 3:1 on sheet, so every filled mark carries an ink outline.
- The dashboard and the report share one stylesheet (`CSS` in `tokscope/report.py`). A design applies to both.

```text
Design [SCREEN, e.g. "the Overview page" | "the Sessions page" | "the HTML report"] for tokscope in its "ink" style.
Output: [mockup on a design canvas | CSS and markup changes in tokscope/report.py and tokscope/dashboard.py].

## Product
tokscope measures the tokens Claude Code uses: per session, skill, subagent and phase. It reads
~/.claude/projects transcripts into local SQLite and shows them in a live local dashboard
(`tokscope serve`: Overview, Projects, Sessions, Skills, Library, Benchmarks, Breakdowns) and
a one-file HTML report (`tokscope report`). Python stdlib only, inline CSS and JS, no build step,
bundled fonts, no CDN, works offline. The owner opens it to answer, in order:
1) How much did I use today, and is that normal?  2) What changed, and why (which skill,
subagent or session)?  3) Where do the tokens go overall? Every screen puts the answer to its
main question first. Use real-looking data; screenshots use `--privacy redacted`, so names may
show as redacted placeholders.

## Style: hand-inked catalogue (after colorfigures.vercel.app)
Light:  paper #f2efe7 (page) · sheet #fbf9f4 (cards) · ink #231e16 (text, outlines)
        muted #6f675a (4.9) · rule #ddd6c8 · shadow #41538f
Dark:   paper #1d1a15 · sheet #27231c · ink #f2efe7 · muted #b0a796 (6.6) · rule #3b3529
        shadow #41538f (same as light)
Data colours, one meaning each, never decoration (fill · text light · text dark):
        main thread  = cobalt  #76a0e2 · #2f5aa8 (5.8) · #8fb3ec (7.3)
        subagents    = mustard #f4b829 · #8a5a00 (5.2) · #f4b829 (8.7)
        pass / down  = mint    #93d3b0 · #1f7a3d (4.7) · #93d3b0 (9.1)
        fail / up    = tomato  #ef6a4c · #b8432a (4.7) · #f08a70 (6.4)
        more series  = blush #f3a6bb, then ink tints; never more than 5 in one chart
Theme: light, dark and System via html[data-theme] and prefers-color-scheme (the :root and
DARK blocks in tokscope/report.py). Every colour has both values and passes WCAG AA.

Type
- Mono = IBM Plex Mono (--mono): numbers, KPI values, token counts, costs, session ids, skill
  and subagent names, labels, buttons, dates, code.
- Sans = Be Vietnam Pro (--sans): sentences: subtitles, notes, empty states, help.
- Labels: mono 11px, uppercase, letter-spacing .08em, muted.
- The main number of a block is its largest text (KPI 22-28px mono 700); weights stay
  400 text, 500 table heads, 600 labels and emphasis, 700 big numbers only.
- Table numbers right-aligned with tabular figures.

Shapes
- Outlines: 1.5px solid ink on cards, tiles and pills; tables use 1px rule lines inside.
- Cards radius 14px, tiles 12px, buttons and filters are 999px pills.
- Flat offset shadow, no blur, one per page: the card that answers the page's main question
  (Overview: Today) gets 10px 12px. Hover on a clickable card: shift -2px, 5px 6px shadow.
  Plain cards and tiles: outline only.
- Chart bars, legend swatches and sparklines' end dots: data fill with a 1.5px ink outline.
- Pills: outline + paper fill; hover or selected = filled ink with paper text.

Content rules
- Up and down are an arrow plus a number ("▲ 59.8×", "▼ 8%"), never colour alone. Up in
  tokens is tomato (more spend), down is mint.
- Main thread vs subagent is always named in a legend or column head, not colour alone.
- Hide what doesn't vary: no 0 rows, no "new" column when nothing is new, no repeated units.
- Show the time window and freshness where numbers can mislead: "last 30 days against the
  range before", "live · updated just now", "history starts 2026-09-21: too short to compare".
- Benchmarks and replays that run Claude say they use quota where they are started; nothing
  calls Claude by itself.
- Empty states say what would appear and how to get it ("No sessions in this range: widen
  the range or run `tokscope ingest`").

Layout
- Order: today / the answer → what changed → breakdowns → history and raw tables (folded).
- Sidebar navigation stays; the theme toggle and help stay in it. The brand mark is ink only.
- KPI tiles: auto-fill grid, min 160px; cards: auto-fill, min 400px, 22px gaps; one column
  under 640px. Wide tables scroll inside their card, never the page.
- Touch targets at least 32px tall; everything reachable by keyboard with a visible focus
  ring; aria-pressed on toggles; reduced motion turns off hover movement and the live pulse.

Don't
- No gradients, glows, emoji or blurred shadows (this removes the report hero's radial
  gradients and the blurred hover shadows on session rows). No fonts beyond the two bundled
  faces, no CDNs.
- No monospace paragraphs. No accent colour that isn't data.
- Don't change layout or behaviour beyond the ask; say so if you think it should change.

Deliver
- Light and dark, at 1440px and 375px, dashboard and report if both are touched.
- A short list of every choice not covered above, so this prompt can be updated.
```

Brand (owner's choice, 2026-10-21): the mark and favicon (`tokscope/brand.py`) are drawn in ink only, no blue or amber. The sidebar mark uses `currentColor` (the theme's ink); the favicon is an ink gauge on a paper square with an ink outline, so it reads on light and dark tab bars.
