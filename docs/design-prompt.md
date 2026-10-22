# Design prompt: the ink style for tokscope

A reusable prompt for designing a tokscope screen (dashboard page or the HTML report) in the "ink" style. It is adapted from the ink prompt of Claude Bot Local (claude-bot-projects `docs/design-prompt.md`), which follows [colorfigures](https://colorfigures.vercel.app/#washer). Fill in the two bracketed lines and paste the whole block.

- Kept from the source: paper, sheet, ink and rule colours, ink outlines, pill buttons, the flat navy shadow, mono labels, and the two bundled faces (tokscope already ships them in `tokscope/assets/fonts/`).
- Changed on purpose: Claude Bot Local's swatches mean a project's state. tokscope has no states; its colours mean data. So the swatches are remapped to series and results below, and "no accent that isn't a state" becomes "no accent that isn't data".
- Changed on purpose: tokscope pages are dense tables and numbers. Shadows go on one card per page, not every card, and tables keep thin rules.
- Text colours were checked for WCAG AA on paper, sheet and chip in both themes (contrast in brackets, the lowest). Light-theme swatch fills are below 3:1 on sheet, so every filled mark carries an ink outline.
- The colours below are the live palette: the `:root` and DARK blocks of `CSS` in `tokscope/web/report.py` (since #6).
- The dashboard and the report share one stylesheet (`CSS` in `tokscope/web/report.py`). A design applies to both.

```text
Design [SCREEN, e.g. "the Overview page" | "the Sessions page" | "the HTML report"] for tokscope in its "ink" style.
Output: [mockup on a design canvas | CSS and markup changes in tokscope/web/report.py and tokscope/web/dashboard.py].

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
        muted #665e51 (5.1) · rule #ddd6c8 · shadow #41538f
Dark:   paper #1d1a15 · sheet #27231c · ink #f2efe7 · muted #b0a796 (5.7) · rule #3b3529
        shadow #41538f (same as light)
Data colours, one meaning each, never decoration (fill · text light · text dark):
        main thread  = cobalt  #76a0e2 · #2f5aa8 (5.4) · #8fb3ec (6.3)
        subagents    = mustard #f4b829 · #8a5a00 (4.8) · #f4b829 (7.5)
        pass / down  = mint    #93d3b0 · #1a6934 (5.4) · #93d3b0 (7.8)
        fail / up    = tomato  #ef6a4c · #a33a23 (5.3) · #f08a70 (5.5)
        more series  = blush #d9708c (dark #c4607d), then a dark and a mid ink tint;
                       "Other" is the palest tint; never more than 5 in one chart.
                       Neighbouring series differ by at least 1.5:1 in luminance.
Theme: light, dark and System via html[data-theme] and prefers-color-scheme (the :root and
DARK blocks in tokscope/web/report.py). Every colour has both values and passes WCAG AA.

Type
- Mono = IBM Plex Mono (--mono): numbers, KPI values, token counts, costs, session ids,
  labels, buttons, dates, code; skill and subagent names only outside tables (meta lines).
- Sans = Be Vietnam Pro (--sans): sentences: subtitles, notes, empty states, help.
- Labels: mono 11px, uppercase, letter-spacing .08em, muted.
- The main number of a block is its largest text (KPI 22-28px mono 600); weights stay
  400 text, 500 table heads, 600 labels, emphasis and big mono numbers; 700 only for sans (mono ships 400-600).
- Table numbers right-aligned with tabular figures, in mono 13px; text cells (names, prompts, notes,
  subagent run lines) stay sans, and headers that hold content (compare titles, markdown) keep their case.
- Buttons, pills, selects and search boxes: mono 12px, weight 400-500. Sentences inside a tile (the "history starts" line) stay sans.

Shapes
- Outlines: 1.5px solid ink on cards, tiles and pills; tables use 1px rule lines inside.
- Cards radius 14px, tiles 12px, buttons and filters are 999px pills.
- Flat offset shadow, no blur, one per page: the card that answers the page's main question
  (Overview: Today) gets 10px 12px. Hover on a clickable card: shift -2px, 5px 6px shadow.
  Plain cards and tiles: outline only.
- Pills: outline + paper fill; hover or selected = filled ink with paper text.
- Chart marks: bars, legend swatches, share segments and columns get a 1px ink edge, dots a
  1.5px one; a hollow dot (paper fill) marks the earlier value. Thin bars are at least 10px
  tall. Lines (sparkline, 7-day average) use the text-safe tokens (--mark-ink, --agent-ink).
- Selection (picked row) = 2px ink outline, never a ring of tint. Primary button is a filled pill
  that inverts to paper on hover. Session rows do not lift on hover (colour only). Diff gap cells are flat chip colour.

Skin tokens (write a new rule once, in `tokscope/web/theme/layout.py`; Classic then needs no copy)
- A skin is tokens plus a short look block. A rule reads a token, never a literal outline, radius or font, so both skins show it.
  Ink value | Classic value. The full list sits above `LAYOUT_TOKEN_CSS` in `layout.py`.
- Outline: `border:var(--line-w) solid var(--line-c)` (1.5px ink | 1px edge). Focus ring: `outline:2px solid var(--focus-c)`.
  Row and day rules: `var(--row-c)`.
- Radius: `--r-card` (cards, 14 | 12), `--r-tile` (rows, KPIs, 12 | 10), `--r-box` (panels, 12 | 8), `--r-ctl` (inputs, selects, chips,
  pill | 8), `--r-btn` (small buttons), `--r-bar` (bar tracks).
- Controls: `--pad-sel`, `--pad-in`, `--pad-chip`, `--pad-btn` (padding), `--in-bg` (input background), `--ctl-size` (text size),
  `--btn-w` (weight).
- Type: `font-family:var(--num-font)` for labels, numbers and controls (mono | sans). A label reads `--lab-case`, `--lab-track`,
  `--lab-size`, `--lab-w` and `--lab-c`. A number cell reads `--cell-size`.
- Charts: `--seg-ring` (ring round a segment), `--trace-c` (line and sparkline colour), `--dot-edge` (edge of a dot), `--bar-h`, `--key-s`.
- Only what differs in kind goes in a skin's look block: the answer-card emphasis (Ink flat navy shadow | Classic tinted outline,
  no shadow), the hero glow, hover and pressed looks, delta style. Add a token only when two or more rules need it.

Motion (working tool: state changes are fast, nothing loops)
- Three durations, as CSS tokens in the layout sheet (`tokscope/web/theme/layout.py`): --t-fast 120ms (press, hover colour),
  --t-state 200ms (toggles, segments, tooltips, delta chip), --t-layout 320ms (row open, sheet, toast, first-paint
  entrances). An exit is 0.7 times its entrance on --ease-exit cubic-bezier(.55,.06,.68,.19); entrances use --ease.
  Any other duration needs a comment that says why (the 600ms live-dot ring, the endless spinner).
- Entrances play on the first paint only. A region that the 2 s poll swaps never replays one. No blur-in, no count-up.
- A live value changes at once; a chip ("+1.2M") shows beside it for 2s: in 200ms, out 140ms.
- The live dot is still. One ring (600ms) shows when a poll finds new data. Offline is a hollow dot.
- Reduced motion keeps opacity and colour and removes travel and scale; an update still shows. The entrance, chip, ring and toast
  keyframes each have an opacity-only twin inside `@media (prefers-reduced-motion:reduce)`; the endless motions (spinner,
  run bar, Classic hero glow) are switched off by their own rule in that media query. There is no global `animation:none`.
- Event map (names after motion-prompt, github.com/showheyohtaki/motion-prompt). Built now: #052 Accordion (open a
  session row or a fold, 320ms), #054 Tooltip (hover or focus a chart bar, 200ms, rises 6px), #056 Toast ("New data
  · reload" and copy feedback, 320ms), #060 Segmented control (range, sort, grouping, 200ms), #068 Step indicator
  (bench and optimize steps), #070 Spinner (inside buttons only), #071 Badge (delta chip, 200ms in, 140ms out),
  #072 Empty state (320ms, first paint), #125 Pulse (live dot, one ring, 600ms), #004 Line draw (first paint only,
  640ms, 2 x --t-layout; published 1.55s). Token only, until the screen exists: #055 Popover (filter list, 280ms), #069 Skeleton
  (static, no shine), #144 Split screen and #057 Tabs (compare).

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
  ring; aria-pressed on toggles; reduced motion removes travel and scale and keeps opacity and colour (see Motion).

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

Brand (owner's choice, 2026-10-21): the mark and favicon (`tokscope/web/theme/brand.py`) are drawn in ink only, no blue or amber. The sidebar mark uses `currentColor` (the theme's ink); the favicon is an ink gauge on a paper square with an ink outline, so it reads on light and dark tab bars.
