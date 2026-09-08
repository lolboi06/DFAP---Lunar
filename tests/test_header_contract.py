# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research

import glob
import os
import pytest

REQUIRED_HEADER_1 = "# Author: Sam Roger X"
REQUIRED_HEADER_2 = "# Component: DFAP WP1 - Data & Entity Research"


def test_header_contract():
    """Verifies that every Python file in the repository includes the mandatory WP1 header."""
    python_files = glob.glob("**/*.py", recursive=True)
    failing_files = []

    for fpath in python_files:
        if "venv" in fpath or ".gemini" in fpath:
            continue

        with open(fpath, "r", encoding="utf-8") as fh:
            lines = [line.strip() for line in fh.readlines()[:10]]

        has_h1 = any(REQUIRED_HEADER_1 in line for line in lines)
        has_h2 = any(REQUIRED_HEADER_2 in line for line in lines)

        if not (has_h1 and has_h2):
            failing_files.append(fpath)

    assert not failing_files, f"Header contract failed for files: {failing_files}"
