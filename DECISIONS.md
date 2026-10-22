# Decisions

## 2026-10-21 · Keep Classic next to Ink

| Decision | Why | Rejected |
| --- | --- | --- |
| The Classic design stays as a second skin with a Classic/Ink button (key `s`), not only for a comparison. | The owner wants both designs and a button to switch between them. | Removing Classic after v1 merged (done in #17, then reverted here). |
| Classic is a token set and a look block (`tokscope/classic.py`), not a frozen copy. Both skins load one layout stylesheet (`tokscope/layout.py`, `<style id="layout">`) for grid, sizes, spacing and structure. New markup gets its layout rules there, so Classic shows it without a copy. (Owner, 2026-10-22, issue #23, option A.) | The copies drifted: about 35 Ink selectors had no Classic match, and each redesign step would have doubled the CSS work. | Copying rules into Classic in each PR; waiting until Classic looks broken. |
| A rule moves into the layout sheet only when both skins have it word for word and no earlier skin rule sets the same property on the same element. | The skin sheets load after the layout sheet. A rule that came later in a skin sheet would lose to the skin rule it used to beat. | Moving every identical rule (changed the phone nav, the Today bars and the reduced-motion fallback). |

## 2026-10-22 · Motion system (issue #23, step 1)

| Decision | Why | Rejected |
| --- | --- | --- |
| Three duration tokens (`--t-fast` 120 ms, `--t-state` 200 ms, `--t-layout` 320 ms) and `--ease-exit` live in the layout sheet. Entrances play on the first paint only (`html.settled`). A live value changes at once and shows a delta chip. | The 2 s poll swaps regions, so every entrance, blur-in and count-up replayed on each update. About 30 durations made the motion uneven. | Keeping the count-up for live values; a duration per rule. |
| Reduced motion: the entrance, chip, ring and toast keyframes have an opacity-only twin in the layout sheet; the spinner, run bar and Classic hero glow are switched off by their own rule; there is no global `animation:none`. | An update must still show for a person who asks for less motion. A global off switch hid it. | `*{animation:none!important}` (what it was). |

## 2026-10-22 · Overview answers "is today normal?" (issue #23, step 2)

| Decision | Why | Rejected |
| --- | --- | --- |
| A typical day is the median of the last 14 active days (a day with at least one request), cumulative to the same local time, shown with a p25 to p75 band only when more than 7 days are active. (Claude's default; the owner had no preference.) | Days off would pull a calendar-day median down and make every working day read as "above typical". | All calendar days; the same weekday only (needs about 4 weeks of history). |
| A change chip shows only with more than 7 days of history. It compares the average per day in the range with the average per day in the window before it, over the days that window has data. A sentence under the strip says so once. Sessions and runs count once per day they appear. | A 30-day range with 10 days before it must not read as -67%. | "History starts ... too short to compare" on every tile. |

## 2026-10-21 · Headless child sessions keep their own totals

| Decision | Why | Rejected |
| --- | --- | --- |
| Child tokens stay on the child row. The parent's totals do not change. | A parent's totals stay comparable with sessions that ran no `claude -p`. Children are shown nested under the parent, so their cost is still visible. | Adding the child tokens to the parent. |
