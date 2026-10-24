# test_privacy setUp closes its connection

**Context:** test_the_database_on_disk_is_never_changed passed or failed with the order and GC timing of earlier tests, and failed once the new tests were added. The setUp connection was left open, so the last connection to close checkpointed the WAL mid-test.

**Decision:** Added conn.close() at the end of setUp so the WAL is checkpointed before the byte comparison. The assertion is unchanged.

**Alternatives:** Leave the flake, or loosen the assertion.

**Impact:** Test-only change. It fixes a latent flake that this feature did not cause.

**If wrong / how to reverse:** Remove the one conn.close() line in tests/test_privacy.py.
