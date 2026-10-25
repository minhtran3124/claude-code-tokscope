import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tokscope.core import markdown
from tokscope.features import library
from tokscope.web import dashboard
from tokscope.core.ingest import connect


def skill(folder, name, description="Does a thing.", body="# Title\n\nText.\n"):
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n{body}")
    return folder


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "h"
        env = mock.patch.dict(os.environ, {"HOME": str(self.home), "TOKSCOPE_HOME": str(self.tmp / "data")})
        env.start()
        self.addCleanup(env.stop)
        self.project = self.home / "work" / "app"
        self.conn = connect(self.tmp / "t.db")
        self.conn.execute("INSERT INTO sessions (session_id, project, cwd, title, prompts) VALUES ('s1', '-p', ?, 't', 1)",
                          (str(self.project / "apps" / "web"),))   # a session in a subfolder still finds the project's skills
        self.conn.commit()
        personal = self.home / ".claude" / "skills"
        skill(personal / "mine-a", "mine-a")
        agents = skill(self.home / ".agents" / "skills" / "linked", "linked")
        (self.home / ".agents" / ".skill-lock.json").write_text(json.dumps({"skills": {"linked": {"source": "someone/skills"}}}))
        (personal / "linked").symlink_to(agents)
        skill(personal / "tool-made", "tool-made")
        (personal / "tool-made" / ".tool-install.json").write_text("{}")
        (personal / "synced").mkdir()                                    # no SKILL.md: not a skill
        project_skills = self.project / ".claude" / "skills"
        skill(project_skills / "proj-own", "proj-own")
        skill(project_skills / "locked", "locked")
        (self.project / "skills-lock.json").write_text(json.dumps({"skills": {"locked": {"source": "x/y"}}}))
        skill(self.project / ".worktrees" / "b" / ".claude" / "skills" / "proj-own", "proj-own")

    def by_dir(self):
        return {(k["scope"], k["dir"]): k for k in library.discover(self.conn)}

    def test_only_skills_without_an_installer_trace_count_as_yours(self):
        found = self.by_dir()
        origin = {d: k["origin"] for (_, d), k in found.items()}
        self.assertEqual(origin, {"mine-a": "mine", "linked": "installed", "tool-made": "installed",
                                  "proj-own": "mine", "locked": "installed"})
        self.assertIn("someone/skills", found[("personal", "linked")]["reason"])
        self.assertIn("~/work/app", {s for s, _ in found})              # the project root, not the session's subfolder

    def test_library_json_overrides_the_guess(self):
        (self.tmp / "data").mkdir()
        (self.tmp / "data" / "library.json").write_text(json.dumps({"mine": ["linked"], "installed": ["mine-a"]}))
        found = self.by_dir()
        self.assertEqual(found[("personal", "linked")]["origin"], "mine")
        self.assertEqual(found[("personal", "mine-a")]["origin"], "installed")

    def test_only_a_listed_file_can_be_read(self):
        k = self.by_dir()[("personal", "mine-a")]
        (k["folder"] / "notes.md").write_text("hi")
        (self.home / "secret.txt").write_text("no")
        self.assertEqual(library.read(k, "notes.md"), ("hi", None))
        self.assertIsNone(library.read(k, "../../../secret.txt")[0])
        self.assertIsNone(library.read(k, "/etc/passwd")[0])

    def _calls(self, rows):
        self.conn.execute("INSERT OR IGNORE INTO sessions (session_id, project, cwd, title, prompts) VALUES ('b1', 'x-tokscope-bench-1', ?, 't', 1)",
                          (str(self.project),))
        for sid, ts, name in rows:
            self.conn.execute("INSERT INTO skill_calls (session_id, ts, skill) VALUES (?, ?, ?)", (sid, ts, name))

    def test_usage_skips_bench_sessions_and_follows_range_and_project(self):
        found = library.discover(self.conn)
        ids = {(k["scope"], k["dir"]): k["id"] for k in found}
        mine = ids[("personal", "mine-a")]
        self._calls([("s1", "2020-01-01T00:00:00.000Z", "mine-a"), ("s1", "2999-01-01T00:00:00.000Z", "mine-a"),
                     ("b1", "2999-01-02T00:00:00.000Z", "mine-a")])
        self.assertEqual(library.usage(self.conn, found)[mine], (2, "2999-01-01T00:00:00.000Z"))
        self.assertEqual(library.usage(self.conn, found, days=30)[mine][0], 1)
        self.assertNotIn(mine, library.usage(self.conn, found, project="-other"))

    def test_same_name_in_two_scopes_keeps_own_counts_and_a_frontmatter_name_matches(self):
        skill(self.home / ".claude" / "skills" / "proj-own", "proj-own")           # personal twin of the project skill
        skill(self.home / ".claude" / "skills" / "folder-x", "fm-name")
        self.conn.execute("INSERT INTO sessions (session_id, project, cwd, title, prompts) VALUES ('s9', '-z', ?, 't', 1)", (str(self.tmp),))
        found = library.discover(self.conn)
        ids = {(k["scope"], k["dir"]): k["id"] for k in found}
        self._calls([("s1", "2999-01-01T00:00:00Z", "proj-own"), ("s9", "2999-01-01T00:00:00Z", "proj-own"),
                     ("s9", "2999-01-02T00:00:00Z", "proj-own"), ("s9", "2999-01-01T00:00:00Z", "fm-name")])
        used = library.usage(self.conn, found)
        personal = ids[("personal", "proj-own")]
        project = next(k["id"] for k in found if k["dir"] == "proj-own" and k["scope"] != "personal")
        self.assertEqual((used[personal][0], used[project][0]), (2, 1))   # each session loads the copy its cwd resolves to
        self.assertEqual(used[ids[("personal", "folder-x")]][0], 1)

    def test_the_page_lists_yours_and_hides_installed_ones(self):
        page = dashboard.page_library(self.conn, dashboard.Filters({}), {}, "full")
        mine = re.findall(r'<a class="sk"[^>]*data-origin="mine"[^>]*>', page)
        self.assertEqual(len(mine), 2)
        self.assertFalse(any("hidden" in a for a in mine))
        self.assertRegex(page, r'<a class="sk"[^>]*data-origin="installed"[^>]*hidden>')
        self.assertIn("Show installed (3)", page)

    def test_a_skill_page_renders_skill_md_and_links_its_files(self):
        k = self.by_dir()[("personal", "mine-a")]
        (k["folder"] / "SKILL.md").write_text("---\nname: mine-a\ndescription: uses `x`\nmodel: opus\n---\nSee [the ref](references/r.md).\n")
        (k["folder"] / "references").mkdir()
        (k["folder"] / "references" / "r.md").write_text("# Ref\n")
        page = dashboard.page_library(self.conn, dashboard.Filters({}), {"skill": [k["id"]]}, "full")
        self.assertIn(f'href="/library?skill={k["id"]}&amp;file=references/r.md">the ref</a>', page)
        self.assertIn("<dt>model</dt><dd>opus</dd>", page)
        self.assertNotIn("<dt>description</dt>", page)            # the header shows it, as Markdown
        self.assertIn("<p>uses <code>x</code></p>", page)
        page = dashboard.page_library(self.conn, dashboard.Filters({}), {"skill": [k["id"]], "file": ["references/r.md"]}, "full")
        self.assertIn("<h1>Ref</h1>", page)

    def test_a_project_filter_keeps_its_skills_and_yours_whatever_the_range(self):
        other = self.home / "work" / "other"
        skill(other / ".claude" / "skills" / "other-own", "other-own")
        self.conn.execute("INSERT INTO sessions (session_id, project, cwd, title, prompts) VALUES ('s2', '-q', ?, 't', 1)", (str(other),))
        self.assertIn("other-own", dashboard.page_library(self.conn, dashboard.Filters({}), {}, "full"))
        page = dashboard.page_library(self.conn, dashboard.Filters({"project": ["-p"], "range": ["7"]}), {}, "full")
        self.assertIn('data-dir="proj-own"', page)          # no load in the range, still listed
        self.assertIn('data-dir="mine-a"', page)
        self.assertNotIn("other-own", page)
        page = dashboard.page_library(self.conn, dashboard.Filters({"project": ["-q"]}), {}, "full")
        self.assertIn('data-dir="other-own"', page)
        self.assertNotIn('data-dir="proj-own"', page)

    def test_a_changed_skill_shows_its_versions_on_its_page(self):
        k = self.by_dir()[("personal", "mine-a")]
        page = dashboard.page_library(self.conn, dashboard.Filters({}), {"skill": [k["id"]]}, "full")
        self.assertNotIn('id="versions"', page)               # one version or none: nothing to compare
        self.conn.executemany("INSERT INTO skill_versions (skill, version, first_seen, last_seen, source) VALUES ('mine-a', ?, ?, ?, 'ingest')",
                              [("aaaaaaaaaaaa", "2026-10-01", "2026-10-01"), ("bbbbbbbbbbbb", "2026-10-10", "2026-10-10")])
        page = dashboard.page_library(self.conn, dashboard.Filters({}), {"skill": [k["id"]]}, "full")
        self.assertIn('id="versions"', page)
        self.assertIn('<a href="#v-mine-a">2 tracked versions</a>', page)
        self.assertIn('<section class="card" id="v-mine-a">', page)

    def test_below_the_full_level_no_skill_text_is_shown(self):
        page = dashboard.page_library(self.conn, dashboard.Filters({}), {}, "redacted")
        self.assertIn("Skill text is hidden", page)
        self.assertNotIn("mine-a", page)


FAKE_LINT = """import json, sys
files = [a for a in sys.argv[1:] if not a.startswith("--") and not a.isdigit()]
open(sys.argv[0] + ".runs", "a").write("x")
out = [{"file": f, "line": 4, "col": 4, "rule": "semicolon", "level": "advisory-free", "match": ";", "message": "Split it."}
       for f in files if "bad" in open(f).read()]
print(json.dumps({"violations": out}))
"""


class SteTest(LibraryTest):
    def setUp(self):
        super().setUp()
        self.lint = self.tmp / "ste-lint.py"
        self.lint.write_text(FAKE_LINT)
        env = mock.patch.dict(os.environ, {"TOKSCOPE_STE_LINT": str(self.lint)})
        env.start()
        self.addCleanup(env.stop)
        self.k = self.by_dir()[("personal", "mine-a")]
        (self.k["folder"] / "SKILL.md").write_text("---\nname: mine-a\n---\nbad; text\n")

    def runs(self):
        return len((self.tmp / "ste-lint.py.runs").read_text()) if (self.tmp / "ste-lint.py.runs").exists() else 0

    def test_the_list_counts_hard_findings_with_one_linter_run_and_reuses_it(self):
        page = dashboard.page_library(self.conn, dashboard.Filters({}), {}, "full")
        self.assertIn('data-ste="1"', page)                     # mine-a
        self.assertIn('data-ste="0"', page)                     # the clean ones
        self.assertEqual(self.runs(), 1)
        dashboard.page_library(self.conn, dashboard.Filters({}), {}, "full")
        self.assertEqual(self.runs(), 1)                        # nothing changed: no second run
        os.utime(self.k["folder"] / "SKILL.md", ns=(1, 1))
        dashboard.page_library(self.conn, dashboard.Filters({}), {}, "full")
        self.assertEqual(self.runs(), 2)                        # an edited file is checked again

    def test_a_finding_links_its_line_and_marks_the_match(self):
        page = dashboard.page_library(self.conn, dashboard.Filters({}), {"skill": [self.k["id"]]}, "full")
        self.assertIn('href="#L4" data-goto="L4">L4</a>', page)
        self.assertIn("<code class=\"line\">bad<mark>;</mark> text</code>", page)
        self.assertIn('<span class="ln" id="L4">bad; text</span>', page)

    def test_without_a_linter_the_tab_says_how_to_get_one(self):
        os.environ["TOKSCOPE_STE_LINT"] = str(self.tmp / "missing.py")
        page = dashboard.page_library(self.conn, dashboard.Filters({}), {"skill": [self.k["id"]]}, "full")
        self.assertIn("Install the asd-ste100 skill", page)


class MarkdownTest(unittest.TestCase):
    def test_raw_html_and_script_links_show_as_text(self):
        out = markdown.render('<script>alert(1)</script>\n\n[x](javascript:alert(1)) and [y](https://a.b/?q=1&r=2)')
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertNotIn("javascript:", out.replace("[x]", ""))
        self.assertIn('<a href="https://a.b/?q=1&amp;r=2">y</a>', out)

    def test_lists_nest_and_keep_their_code_blocks(self):
        out = markdown.render("Steps:\n1. One\n   - sub `a|b`\n2. Two\n\n   ```sh\n   echo hi\n   ```\n")
        self.assertIn("<p>Steps:</p><ol><li>One<ul><li>sub <code>a|b</code></li></ul></li><li>Two<pre>", out)
        self.assertIn("echo hi</code></pre></li></ol>", out)

    def test_bold_and_links_may_wrap_code(self):
        self.assertEqual(markdown.render("**Write `a*b` here** and [the `x`](https://e.x)"),
                         '<p><strong>Write <code>a*b</code> here</strong> and <a href="https://e.x">the <code>x</code></a></p>')

    def test_tables_fences_and_frontmatter(self):
        meta, body = markdown.frontmatter("---\nname: n\ndescription: >\n  long\n  text\n---\nBody")
        self.assertEqual(meta, {"name": "n", "description": "long text"})
        self.assertEqual(body, "Body")
        out = markdown.render("| a | b |\n|---|---|\n| **1** | 2 |\n\n```\n<b>\n```")
        self.assertIn("<td><strong>1</strong></td>", out)
        self.assertIn("<pre><code>&lt;b&gt;</code></pre>", out)


if __name__ == "__main__":
    unittest.main()
