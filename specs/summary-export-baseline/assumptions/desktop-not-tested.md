# Desktop app not exercised

**Context:** The acceptance criteria mention the desktop app, but no Electron app is run in this workflow.

**Decision:** Verified in Chromium only. Downloads use `<a download>` and the clipboard API, which work in Electron on 127.0.0.1.

**Alternatives:** Build and run the Electron app.

**Impact:** The owner should confirm downloads and Copy in the desktop window.

**How to reverse:** Nothing to reverse in code; fix in the desktop main process if Electron blocks them.
