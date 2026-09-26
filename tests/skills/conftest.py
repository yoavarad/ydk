"""Make the gh-issue-to-tasks scripts importable for tests."""

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "gh-issue-to-tasks" / "scripts"
sys.path.insert(0, str(SCRIPTS))
