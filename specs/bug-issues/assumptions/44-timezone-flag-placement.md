# Assumption (issue 44): --timezone placement

- **Context:** The issue asks for a --timezone option or TOKSCOPE_TZ.
- **Decision:** Added --timezone to serve, summary, report and open. TOKSCOPE_TZ works everywhere.
- **Alternatives:** A global flag before the subcommand.
- **Impact:** Low.
- **How to reverse:** Move the option to a global flag, or keep only TOKSCOPE_TZ.
