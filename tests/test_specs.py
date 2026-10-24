import re
import unittest
from pathlib import Path

SPEC = Path(__file__).resolve().parent.parent / "specs" / "analytics-54-57"
TITLES = {"55": "budgets", "56": "context"}  # GitHub issue titles: #55 Budgets and alerts, #56 Context findings


class SpecIssueNumbers(unittest.TestCase):
    def test_plan_and_summary_map_55_and_56_to_the_github_titles(self):
        for name in ("PLAN.md", "SUMMARY.md"):
            text = (SPEC / name).read_text()
            for num, word in TITLES.items():
                hits = re.findall(rf"#{num}\b[^\n|]{{0,12}}?(budgets|context)", text, re.I)
                self.assertTrue(hits, f"{name}: no '#{num} <name>' mention")
                self.assertTrue(all(h.lower() == word for h in hits), f"{name}: #{num} must be {word}")


if __name__ == "__main__":
    unittest.main()
