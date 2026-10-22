# Decisions

## 2026-10-21 · Keep Classic next to Ink

| Decision | Why | Rejected |
| --- | --- | --- |
| The Classic design stays as a second skin with a Classic/Ink button (key `s`), not only for a comparison. | The owner wants both designs and a button to switch between them. | Removing Classic after v1 merged (done in #17, then reverted here). |
| Classic is a token set and a look block (`tokscope/classic.py`), not a frozen copy. Both skins load one layout stylesheet (`tokscope/layout.py`, `<style id="layout">`) for grid, sizes, spacing and structure. New markup gets its layout rules there, so Classic shows it without a copy. (Owner, 2026-10-22, issue #23, option A.) | The copies drifted: about 35 Ink selectors had no Classic match, and each redesign step would have doubled the CSS work. | Copying rules into Classic in each PR; waiting until Classic looks broken. |
| A rule moves into the layout sheet only when both skins have it word for word and no earlier skin rule sets the same property on the same element. | The skin sheets load after the layout sheet. A rule that came later in a skin sheet would lose to the skin rule it used to beat. | Moving every identical rule (changed the phone nav, the Today bars and the reduced-motion fallback). |

## 2026-10-21 · Headless child sessions keep their own totals

| Decision | Why | Rejected |
| --- | --- | --- |
| Child tokens stay on the child row. The parent's totals do not change. | A parent's totals stay comparable with sessions that ran no `claude -p`. Children are shown nested under the parent, so their cost is still visible. | Adding the child tokens to the parent. |
