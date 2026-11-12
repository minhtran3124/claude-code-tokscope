# Design prompt: the Indigo style for tokscope

A reusable prompt for designing a tokscope screen (dashboard page or the HTML report) in the "Indigo" style, the only look
since #257 (it replaced Ink). Fill in the two bracketed lines and paste the whole block.

- The colours below are the live palette: the `:root` and DARK blocks of `CSS` in `tokscope/web/report/styles.py`.
- The dashboard and the report share one stylesheet. A design applies to both.
- Contrast (WCAG, measured 2026-11-12 from the tokens): muted text is at least 4.8:1 on page, card and sunken grounds in
  both themes; the five chip tints and the ok / warn / bad pill fills keep their text at 4.5:1 or more.

```text
Design [SCREEN, e.g. "the Overview page" | "the Sessions page" | "the HTML report"] for tokscope in its "Indigo" style.
Output: [mockup on a design canvas | CSS and markup changes in tokscope/web/report/ and tokscope/web/dashboard/].

## Product
tokscope measures the tokens Claude Code uses: per session, skill, subagent and phase. It reads
~/.claude/projects transcripts into local SQLite and shows them in a live local dashboard
(`tokscope serve`: Overview, Sessions, Breakdowns, Projects, Library, Optimize, Benchmarks, Managed, Settings) and
a one-file HTML report (`tokscope report`). Python stdlib only, inline CSS and JS, no build step,
bundled fonts, no CDN, works offline. The owner opens it to answer, in order:
1) How much did I use today, and is that normal?  2) What changed, and why (which skill,
subagent or session)?  3) Where do the tokens go overall? Every screen puts the answer to its
main question first. Use real-looking data; screenshots use `--privacy redacted`, so names may
show as redacted placeholders.

## Style: Indigo (cool white surfaces, one indigo accent, soft tinted chips)
Light:  page #F5F5FA · card #FFFFFF · sunken #EEEEF6 (hover, notes, bar tracks) · text #1B1B2F
        muted #66667F · line #E2E2EE / strong line #D2D2E2 · accent #4B4FD8 (text on accent #FFFFFF)
        accent soft #E9E9FC / accent line #C9CAF5 (the selected state)
Dark:   page #12121C · card #1B1B29 · sunken #262638 (bar tracks; hover and chips #2B2B3E) · text #E9E9F6 · muted #9A9AB5
        line #2D2D42 / #3A3A55 · accent #8B8EF5 (text on accent #12122A) · accent soft #25264A / #3C3E7A
Status (text / fill), status only, never decoration:
        ok #1C7C54 / #E6F6EE (dark #5DD3A0 / #163428) · warn #9A6212 / #FDF4E3 (dark #E8B45C / #3A2D12)
        bad #B8344A / #FBE3E7 (dark #F08196 / #3E1D26)
Data series, one meaning each:
        main thread = accent indigo · subagents = teal #1E9C86 (dark #4CC9AE) · 7-day average = amber #845411 (dark #F0C47A)
        more series = pink #C9479B, orange #D9702A, grey #7A7A92; "Other" is the palest; never more than 5 in one chart.
Chips: five soft tint pairs (--k0 ... --k4 with --k0-ink ... --k4-ink). A skill name always gets the same tint
        (`widgets.hue`, 32-bit FNV-1a over the name, mod 5; the page script has the same `hue`). A subagent type is the
        neutral chip.
Theme: light, dark and System via html[data-theme] and prefers-color-scheme. Every colour has both values.

Type
- Sans = Hanken Grotesk (--sans, 400-800): interface text, labels, numbers (tabular figures from `body`).
- Mono = DM Mono (--mono, 400 and 500 only; IBM Plex Mono covers Vietnamese): ids, code, model names, times in tables.
- Base 15px, line height 1.5. page h1 28px (22px in the report), card h2 17px, h3 1rem, weight 700.
- Table heads and group labels: 11px, uppercase, letter-spacing .06em, muted. Stat-tile labels are sentence case, 13px, muted.
- The main number of a block is its largest text (stat tile 19px, 24px on the Overview, weight 700). Table numbers right-aligned.

Shapes
- Radius: 8px buttons, inputs, menu items; 12px cards and tables; 99px pills; 6px chips.
- Cards at rest: 1px line, no shadow. Shadow (0 8px 30px rgba(27,27,47,.14)) only on popovers, dialogs, the compare
  tray and card hover.
- Selected state (menu item, segment, picked row): accent soft background, accent text (--on-bg, --on-fg, --on-line).
- Segmented controls are joined (one outline, the selected segment filled). Primary button is filled accent.
- Status pills are soft fills (ok / warn / bad), not outlines. Icons: the 24px stroke set in
  `tokscope/web/theme/icons.py` (2px stroke, round caps, currentColor), inline SVG.
- Charts: stacked bars main (indigo) under subagents (teal); sparklines are a 1.5px line with a light fill under it.

Tokens (write a new rule once, in `tokscope/web/theme/layout.py`)
- The look is tokens plus a short look block in `report/styles.py`. A rule reads a token, never a literal colour.
  The full list sits above `LAYOUT_TOKEN_CSS` in `layout.py`.
- Outline: `border:var(--line-w) solid var(--line-c)`. Focus ring: `outline:2px solid var(--focus-c)` (accent).
- Radius: `--r-card`, `--r-tile`, `--r-box`, `--r-ctl`, `--r-btn`, `--r-bar`. Controls: `--pad-*`, `--in-bg`, `--ctl-size`, `--btn-w`.
- Labels read `--lab-case`, `--lab-track`, `--lab-size`, `--lab-w`, `--lab-c`; numbers `--num-font` (sans).
- Add a token only when two or more rules need it.

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
  run bar) are switched off by their own rule in that media query. There is no global `animation:none`.
- Event map (names after motion-prompt, github.com/showheyohtaki/motion-prompt). Built now: #052 Accordion (open a
  session row or a fold, 320ms), #054 Tooltip (hover or focus a chart bar, 200ms, rises 6px), #056 Toast ("New data
  · reload" and copy feedback, 320ms), #060 Segmented control (range, sort, grouping, 200ms), #068 Step indicator
  (bench and optimize steps), #070 Spinner (inside buttons only), #071 Badge (delta chip, 200ms in, 140ms out),
  #072 Empty state (320ms, first paint), #125 Pulse (live dot, one ring, 600ms), #004 Line draw (first paint only,
  640ms, 2 x --t-layout; published 1.55s). Token only, until the screen exists: #055 Popover (filter list, 280ms), #069 Skeleton
  (static, no shine), #144 Split screen and #057 Tabs (compare).

Content rules
- Up and down are an arrow plus a number ("▲ 59.8×", "▼ 8%"), never colour alone.
- Main thread vs subagent is always named in a legend or column head, not colour alone.
- Hide what doesn't vary: no 0 rows, no "new" column when nothing is new, no repeated units.
- Show the time window and freshness where numbers can mislead.
- Benchmarks and replays that run Claude say they use quota where they are started; nothing calls Claude by itself.
- Empty states say what would appear and how to get it.

Layout
- Left menu 248px with icons and group labels (Usage, Workspace, Connect, System); below 640px it becomes a top bar
  with a Menu button. Page head: h1, a muted subtitle, actions on the right; filters (range segments, Project, Model, Skill).
- Two-column pages: main column plus a 300px side column; one column below 1100px.
- Stat tiles: separate cards, 3 a row, 2 on a phone. Wide tables scroll inside their box, never the page.
- Touch targets at least 44px on a phone; everything reachable by keyboard with a visible focus ring; aria-pressed on toggles.

Don't
- No gradients, glows or emoji. No fonts beyond the bundled faces, no CDNs.
- No colour that is not the accent, a status or a data series.
- Don't change layout or behaviour beyond the ask; say so if you think it should change.

Deliver
- Light and dark, at 1440px and 375px, dashboard and report if both are touched.
- A short list of every choice not covered above, so this prompt can be updated.
```

Brand: the mark and favicon (`tokscope/web/theme/brand.py`) are a white gauge on an indigo (#4B4FD8) rounded square.
