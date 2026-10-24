# Assumption (issue 44): Label formats

- **Context:** Chart notes name the zone.
- **Decision:** IANA name when set, otherwise the system zone abbreviation (for example +07).
- **Alternatives:** Always show a UTC offset.
- **Impact:** Cosmetic.
- **How to reverse:** Change the label helper to always print the UTC offset.
