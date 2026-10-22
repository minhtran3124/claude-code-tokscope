"""What the report's queries share: the SQL sum that counts a request's tokens."""


TOKENS = "(input + cache_read + cache_write_5m + cache_write_1h + output)"
