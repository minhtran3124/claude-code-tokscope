# Deferred tools count 0 tokens

**Context:** Of 827 MCP tool entries in local shape records, 322 have defer_loading true. Only their names are sent, not their definitions.

**Decision:** Only non-deferred MCP tools are summed per server. A server whose tools are all deferred shows a dash, not 0.

**Alternatives:** Count deferred definitions too. This would overstate the prefix.

**Impact:** Definition tokens and the unused-server finding can be lower than a server's full definition size, or absent.

**If wrong / how to reverse:** Drop the defer_loading filter in the per-server sum in the definition-token query. No data migration.
