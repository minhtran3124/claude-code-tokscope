# Research: package layout for `tokscope/`

Date: 2026-10-22. Before this change, `tokscope/` was flat: 23 modules side by side, from the 15-line
`brand.py` to the 1,835-line `dashboard.py`. Nothing in the tree showed which modules read transcripts, which serve
pages and which start paid `claude -p` runs.

## What common practice says

- **Group by purpose ("package by feature/layer"), not by file type.** A reader should find a module from what it
  does. Python apps of this size (Django apps, `pip`'s `_internal/`, `httpie`) use a few sub-packages, each with one
  clear job, and keep the entry point at the top.
- **Keep the public entry point stable.** `pyproject.toml` (`tokscope.cli:main`), `bin/tokscope`
  (`python3 -m tokscope.cli`) and the mod all call `tokscope.cli`, so `cli.py` stays at the root.
- **Dependencies point one way.** The core (transcripts → SQLite) must not import the web layer. Features may use the
  core. The web layer may use everything.
- **Data files are not code.** Fonts and the default phase map go in one `assets/` folder that is package data.
- **Stay shallow.** At most two levels. A deeper tree costs more import churn than it saves.
- **`src/` layout** (`src/tokscope/`) protects against importing the clone by mistake in tests. It is not used here,
  because `paths.home()` finds the clone (and its `data/`) from the package's position and `bin/tokscope` runs from
  the clone. Moving to `src/` would change where a clone keeps its data.

## Layout chosen

```
tokscope/
  __init__.py      version
  cli.py           entry point: argument parsing, terminal output
  paths.py         data home and bundled files
  assets/          fonts/*.woff2, phases.json (package data)
  core/            transcripts to SQLite: ingest, calls, pricing, privacy, skills (versions), markdown
  features/        what the pages manage: library, projects (MCP), changes
  integrations/    outside services: managed (ant CLI), registry (MCP Registry)
  experiments/     paid runs of claude -p: bench, replay, optimize
  web/             HTML: dashboard (server and pages), report, charts
    theme/         look: layout, classic, brand, fonts
```

Dependency rule, checked by `tests/test_layout.py`:
- `core` imports only `core` and `paths`. `skills` sits in core because ingest hashes skill versions as it reads;
  `markdown` sits in core because the library parses frontmatter with it.
- `web` is imported by nothing but `cli` and `web`.

## Not done here (follow-ups)

- **Split `web/dashboard.py`** (1,835 lines) into a server module, one module per page, and the page scripts.
  Split `web/report.py` (1,022 lines) the same way. This is the larger maintainability gain. It touches every UI
  test, so it needs its own PR with screenshots.
- `core/ingest.py` and `core/skills.py` import each other inside functions. That cycle could break up with a
  small `core/transcript.py` for the shared regexes.
