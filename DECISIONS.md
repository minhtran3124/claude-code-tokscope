# Decisions

## 2026-10-21 · Headless child sessions keep their own totals

| Decision | Why | Rejected |
| --- | --- | --- |
| Child tokens stay on the child row. The parent's totals do not change. | A parent's totals stay comparable with sessions that ran no `claude -p`. Children are shown nested under the parent, so their cost is still visible. | Adding the child tokens to the parent. |
