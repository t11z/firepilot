"""Shared config discovery utilities for FirePilot CI scripts.

Provides functions for discovering and loading firewall rule files from the
firewall-configs/ directory tree. Imported by gate3-dry-run.py, gate4-deploy.py,
and drift-check.py to avoid duplication.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RULEBASE_MANIFEST = "_rulebase.yaml"

# ---------------------------------------------------------------------------
# Config discovery
# ---------------------------------------------------------------------------


def discover_rule_dirs(config_dir: Path) -> list[tuple[str, str, Path]]:
    """Return (folder, position, dir_path) for each {folder}/{position}/ directory.

    Enumerates all subdirectories of config_dir that contain a _rulebase.yaml
    manifest file. Results are sorted for deterministic ordering.

    Args:
        config_dir: Root of the firewall-configs/ tree.

    Returns:
        List of (folder_name, position_name, directory_path) tuples.
    """
    results: list[tuple[str, str, Path]] = []
    for folder_dir in sorted(config_dir.iterdir()):
        if not folder_dir.is_dir():
            continue
        for position_dir in sorted(folder_dir.iterdir()):
            if not position_dir.is_dir():
                continue
            manifest = position_dir / RULEBASE_MANIFEST
            if not manifest.exists():
                continue
            results.append((folder_dir.name, position_dir.name, position_dir))
    return results


def load_rule_files(position_dir: Path) -> list[dict]:
    """Load all rule YAML files (excluding _rulebase.yaml) from a position dir.

    Args:
        position_dir: The {folder}/{position}/ directory.

    Returns:
        List of parsed YAML dicts for each rule file, each annotated with a
        '_source_file' key pointing to the originating file path.
    """
    rules: list[dict] = []
    for yaml_file in sorted(position_dir.glob("*.yaml")):
        if yaml_file.name == RULEBASE_MANIFEST:
            continue
        with yaml_file.open() as fh:
            data = yaml.safe_load(fh)
        if isinstance(data, dict):
            data["_source_file"] = str(yaml_file)
            rules.append(data)
    return rules
