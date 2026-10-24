# Assumption (issue 42): Use PYTHONPATH approach

- **Context:** The issue offered two options: PYTHONPATH, or exporting the original cwd and resolving paths in cli.py.
- **Decision:** Used PYTHONPATH and left cli.py unchanged.
- **Alternatives:** A TOKSCOPE_CWD env var with path resolution in cli.py.
- **Impact:** Smaller change. Any existing PYTHONPATH is kept after the clone path.
- **How to reverse:** Replace the PYTHONPATH line in bin/tokscope with a cwd export and resolve paths in cli.py.
