"""The package layout (docs/research-package-layout.md): imports point one way, so the core never needs the pages."""
import ast
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "tokscope"


def imports(f):
    """The tokscope modules one file imports, as dotted names under tokscope ("core.ingest", "paths")."""
    here = f.relative_to(PKG).parent.parts
    out = set()
    for node in ast.walk(ast.parse(f.read_text())):
        if isinstance(node, ast.ImportFrom) and node.level:
            base = list(here[:len(here) - node.level + 1])
            mod = base + (node.module.split(".") if node.module else [])
            out.update(".".join(mod + ([] if node.module else [a.name])) for a in node.names)
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("tokscope"):
            out.add(node.module.removeprefix("tokscope").lstrip("."))
    return out


class LayoutTest(unittest.TestCase):
    def test_the_core_imports_only_the_core_and_paths(self):
        for f in (PKG / "core").rglob("*.py"):
            for m in imports(f):
                self.assertTrue(m.startswith("core") or m in ("paths", "__version__"), f"{f.name} imports {m}")

    def test_only_cli_and_web_import_web(self):
        for f in PKG.rglob("*.py"):
            top = f.relative_to(PKG).parts[0]
            if top in ("cli.py", "web"):
                continue
            for m in imports(f):
                self.assertFalse(m.startswith("web"), f"{f.relative_to(PKG)} imports {m}")

    def test_no_module_is_left_at_the_top_but_the_entry_point_and_paths(self):
        self.assertEqual(sorted(p.name for p in PKG.glob("*.py")), ["__init__.py", "cli.py", "paths.py"])


if __name__ == "__main__":
    unittest.main()
