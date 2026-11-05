# UAT #195: real sessions on an approved run

Before = parent commit 679d46d, after = this branch. Screenshots: `195-before-1440.png`, `195-after-1440.png`, `195-before-375.png`, `195-after-375.png`. Seeded run: old 6 loads (1 failed), new 3 loads, 4 loads of a hand-edited version.

| Criterion | Result | Seen |
|---|---|---|
| AC1 old and new side by side: loads, median tokens, median cost, error rate | pass | 6 / 3 loads, 120.0K / 80.0K, $0.93 / $0.61, 17% / 0% |
| AC2 "too few to compare" under 5 loads | pass | note for the new side (3 loads) only |
| AC3 other versions and loads outside the boundary not counted | pass | 4 hand-edited loads absent from both sides |
| No layout break at 375 px | pass | card fits, table readable |
