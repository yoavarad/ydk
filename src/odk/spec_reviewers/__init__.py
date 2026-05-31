"""Built-in spec reviewer YAML definitions.

This package ships the default N01-N10 reviewer YAML files.
On ``odk init``, these are copied to ``.odk/spec-reviewers/``
so projects can customise thresholds, prompts, and tools.
"""

from __future__ import annotations

from pathlib import Path

REVIEWERS_DIR = Path(__file__).parent
