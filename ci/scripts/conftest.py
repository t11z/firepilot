"""Pytest configuration for ci/scripts/ tests.

Python's standard import system does not support module names containing
hyphens (e.g. gate3-dry-run.py, drift-check.py). This conftest registers
those modules under their underscore aliases before test collection so that
test files can import them with standard `import` statements.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent

_HYPHENATED_MODULES: dict[str, str] = {
    "gate3_dry_run": "gate3-dry-run.py",
    "gate4_deploy": "gate4-deploy.py",
    "drift_check": "drift-check.py",
    "retry_deploy": "retry-deploy.py",
}


def _register(alias: str, filename: str) -> None:
    """Load a hyphenated .py file and register it under *alias* in sys.modules."""
    if alias in sys.modules:
        return
    path = _SCRIPTS_DIR / filename
    spec = importlib.util.spec_from_file_location(alias, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]


for _alias, _filename in _HYPHENATED_MODULES.items():
    _register(_alias, _filename)
