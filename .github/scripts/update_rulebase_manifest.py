#!/usr/bin/env python3
"""FirePilot — Update or create a ``_rulebase.yaml`` manifest file.

Appends a new rule name to the ``rule_order`` list in an existing
``_rulebase.yaml``, or creates a new manifest if none exists at the
specified path.

Per ADR-0007, every new rule addition requires atomic changes to two files:
the rule YAML file *and* the ``_rulebase.yaml`` ordering manifest.  This
script handles the manifest half of that requirement.  CI/CD validation
(Gate 1 JSON Schema, Gate 2 OPA) enforces that both files are consistent —
a manifest entry without a corresponding rule file, or vice versa, is a
hard validation failure.

The script is idempotent: if the rule name is already present in
``rule_order``, it logs a warning and exits successfully without
duplicating the entry.

Usage::

    python update_rulebase_manifest.py \\
        --manifest firewall-configs/shared/pre/_rulebase.yaml \\
        --rule-name allow-web-to-app \\
        --folder shared \\
        --position pre
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Rulebase manifest schema version as defined in ADR-0007.
SCHEMA_VERSION: int = 1


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    """Parse an existing ``_rulebase.yaml`` manifest from disk.

    Args:
        manifest_path: Absolute or relative path to the manifest file.

    Returns:
        Parsed manifest as a dictionary.  Returns an empty dict if the file
        is empty or contains only null.

    Raises:
        yaml.YAMLError: If the file contains invalid YAML.
        OSError: If the file cannot be opened.
    """
    with open(manifest_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data if isinstance(data, dict) else {}


def create_manifest(folder: str, position: str) -> dict[str, Any]:
    """Return a new ``_rulebase.yaml`` manifest dict with an empty rule_order.

    Per ADR-0007, a manifest must contain ``schema_version``, ``folder``,
    ``position``, and ``rule_order``.

    Args:
        folder: SCM folder name.  Must match the parent directory name.
        position: Rule position — ``"pre"`` or ``"post"``.

    Returns:
        New manifest dictionary with ``rule_order: []``.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "folder": folder,
        "position": position,
        "rule_order": [],
    }


def append_rule(manifest: dict[str, Any], rule_name: str) -> dict[str, Any]:
    """Append ``rule_name`` to the manifest's ``rule_order`` list.

    Skips insertion if the rule name is already present, making the
    operation idempotent (re-running the workflow on the same issue does
    not create duplicate entries).

    Args:
        manifest: Parsed or newly-created manifest dictionary.
        rule_name: Name of the security rule to append.

    Returns:
        Updated manifest dictionary (mutated in place and returned).
    """
    rule_order = manifest.get("rule_order")
    if not isinstance(rule_order, list):
        # Defensive: treat a missing or wrong-type rule_order as empty.
        rule_order = []

    if rule_name in rule_order:
        print(
            f"WARNING: Rule '{rule_name}' is already present in rule_order — "
            "skipping duplicate insertion.",
            file=sys.stderr,
        )
    else:
        rule_order.append(rule_name)

    manifest["rule_order"] = rule_order
    return manifest


def write_manifest(manifest: dict[str, Any], manifest_path: Path) -> None:
    """Serialise a manifest dictionary to ``_rulebase.yaml``.

    Creates parent directories if they do not yet exist.

    Args:
        manifest: Manifest dictionary to serialise.
        manifest_path: Destination file path.

    Raises:
        OSError: If the file or its parent directories cannot be created.
    """
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        # sort_keys=False preserves the canonical field order defined in ADR-0007:
        # schema_version → folder → position → rule_order.
        yaml.dump(
            manifest,
            fh,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse and return command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Update or create a FirePilot _rulebase.yaml ordering manifest. "
            "Appends the given rule name to rule_order, creating the manifest "
            "if it does not yet exist."
        )
    )
    parser.add_argument(
        "--manifest",
        required=True,
        type=Path,
        metavar="PATH",
        help="Path to the _rulebase.yaml file.  Created if absent.",
    )
    parser.add_argument(
        "--rule-name",
        required=True,
        metavar="NAME",
        help="Security rule name to append to rule_order.",
    )
    parser.add_argument(
        "--folder",
        required=True,
        metavar="FOLDER",
        help="SCM folder name.  Used when creating a new manifest.",
    )
    parser.add_argument(
        "--position",
        required=True,
        choices=["pre", "post"],
        metavar="POSITION",
        help="Rule position ('pre' or 'post').  Used when creating a new manifest.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point — update or create the ``_rulebase.yaml`` manifest.

    Flow:
        1. If the manifest file exists: load it.
        2. If not: create a new manifest with ``rule_order: []``.
        3. Append the rule name to ``rule_order`` (idempotent).
        4. Write the updated manifest back to disk.
    """
    args = parse_args()
    manifest_path: Path = args.manifest
    rule_name: str = args.rule_name
    folder: str = args.folder
    position: str = args.position

    if manifest_path.exists():
        print(f"Loading existing manifest: {manifest_path}")
        try:
            manifest = load_manifest(manifest_path)
        except yaml.YAMLError as exc:
            print(f"ERROR: Failed to parse existing manifest: {exc}", file=sys.stderr)
            sys.exit(1)
        except OSError as exc:
            print(f"ERROR: Failed to read manifest file: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"Manifest not found. Creating new manifest: {manifest_path}")
        manifest = create_manifest(folder, position)

    manifest = append_rule(manifest, rule_name)

    try:
        write_manifest(manifest, manifest_path)
    except OSError as exc:
        print(f"ERROR: Failed to write manifest: {exc}", file=sys.stderr)
        sys.exit(1)

    rule_order: list[str] = manifest.get("rule_order", [])  # type: ignore[assignment]
    print(
        f"Manifest written to {manifest_path}. "
        f"rule_order ({len(rule_order)} rule(s)): {rule_order}"
    )


if __name__ == "__main__":
    main()
