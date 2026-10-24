# Overview line ignores model and skill filters

**Context:** The session start is not tied to a skill or model choice.

**Decision:** The Overview Session start card uses the range and project filters only. No model or skill filter is applied.

**Alternatives:** Apply every filter. This would mostly empty the card.

**Impact:** The card can show sessions that the model or skill filter hides from other cards.

**If wrong / how to reverse:** Pass the model and skill filters into the card query.
