"""Apptainer-only pytest temp-root override for the unchanged cattrs verifier."""

import os


_pytest_options = os.environ.get("PYTEST_ADDOPTS", "")
if _pytest_options and "--basetemp" not in _pytest_options:
    os.environ["PYTEST_ADDOPTS"] = (
        f"{_pytest_options} --basetemp=/tmp/frontier-memory-agent-output/pytest-basetemp"
    )
