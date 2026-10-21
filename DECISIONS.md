# Decisions

## 2026-10-21 · Keep Classic next to Ink

| Decision | Why | Rejected |
| --- | --- | --- |
| The Classic design stays as a second skin with a Classic/Ink button (key `s`), not only for a comparison. | The owner wants both designs and a button to switch between them. | Removing Classic after v1 merged (done in #17, then reverted here). |
| Classic is a frozen copy of the old stylesheet (`tokscope/classic.py`). New markup gets Ink styles first; Classic gets a fix only when something looks broken in it. | Keeps the cost of a second design low. | Keeping both designs in step for every change. |

## 2026-10-21 · Headless child sessions keep their own totals

| Decision | Why | Rejected |
| --- | --- | --- |
| Child tokens stay on the child row. The parent's totals do not change. | A parent's totals stay comparable with sessions that ran no `claude -p`. Children are shown nested under the parent, so their cost is still visible. | Adding the child tokens to the parent. |
