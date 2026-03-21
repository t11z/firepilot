#!/usr/bin/env python3
"""build-opa-input.py — Assemble the OPA input JSON for a given firewall-configs directory.

Usage:
    python ci/scripts/build-opa-input.py <directory> [--folder FOLDER] [--position POSITION]
                                                      [--config CONFIG_FILE]

    <directory> must contain:
        _rulebase.yaml   — the rulebase manifest
        {name}.yaml      — one or more rule files (if any are declared)

    --folder FOLDER      Override the derived folder name (default: parent directory name)
    --position POSITION  Override the derived position name (default: directory name)
    --config CONFIG_FILE Path to firepilot.yaml; if provided, adds zone_mapping to OPA input

Output:
    JSON printed to stdout suitable for piping to `opa eval -i /dev/stdin`.

Examples:
    # Valid fixture — folder/position derived from path (shared/pre), with zone mapping
    python ci/scripts/build-opa-input.py firewall-configs/shared/pre/ \\
        --config firepilot.yaml \\
        | opa eval -i /dev/stdin -d ci/policies/firepilot.rego \\
            'data.firepilot.validate.deny'

    # Invalid fixture — override folder/position to isolate the intended violation
    python ci/scripts/build-opa-input.py ci/fixtures/invalid/missing-firepilot-tag/ \\
        --folder shared --position pre \\
        | opa eval -i /dev/stdin -d ci/policies/firepilot.rego \\
            'data.firepilot.validate.deny'

    # folder-mismatch fixture — override with a different folder name to trigger mismatch
    python ci/scripts/build-opa-input.py ci/fixtures/invalid/folder-mismatch/ \\
        --folder production --position pre \\
        | opa eval -i /dev/stdin -d ci/policies/firepilot.rego \\
            'data.firepilot.validate.deny'

    # Topology violation fixture — supply config to activate topology policies
    python ci/scripts/build-opa-input.py ci/fixtures/invalid/internet-to-database/ \\
        --folder shared --position pre \\
        --config ci/fixtures/invalid/internet-to-database/firepilot.yaml \\
        | opa eval -i /dev/stdin -d ci/policies/firepilot.rego \\
            'data.firepilot.validate.deny'

Exit codes:
    0 — input JSON emitted successfully
    1 — directory not found, _rulebase.yaml missing, or YAML parse error

Input schema produced (matches firepilot.rego expectation):
    {
      "manifest":     { ... },         # deserialized _rulebase.yaml
      "rule_files":   { name: {...} }, # map of filename → deserialized YAML
      "directory":    {                # directory metadata (from filesystem or overrides)
        "folder":   "<parent-dir-name>",
        "position": "<dir-name>"       # must be "pre" or "post" for valid configs
      },
      "zone_mapping": { ... }          # present only when --config is supplied (ADR-0008)
    }
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print(
        "Error: PyYAML is required. Install with: pip install pyyaml",
        file=sys.stderr,
    )
    sys.exit(1)

MANIFEST_FILENAME = "_rulebase.yaml"
# firepilot.yaml is the operator configuration file (ADR-0012). Its zones section
# is the zone topology mapping (ADR-0008). Skip it if encountered so that fixture
# directories can colocate a firepilot.yaml for test convenience without it being
# misidentified as a rule file.
ZONE_MAPPING_FILENAME = "firepilot.yaml"


def load_yaml(path: Path) -> dict:
    """Load and parse a YAML file, returning its contents as a dict.

    Args:
        path: Filesystem path to the YAML file.

    Returns:
        Parsed YAML content as a dictionary.

    Raises:
        SystemExit: On file not found or YAML parse error.
    """
    try:
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except FileNotFoundError:
        print(f"Error: File not found: {path}", file=sys.stderr)
        sys.exit(1)
    except yaml.YAMLError as exc:
        print(f"Error: Failed to parse YAML file {path}: {exc}", file=sys.stderr)
        sys.exit(1)


def load_zone_mapping(zones_path: Path) -> dict:
    """Load firepilot.yaml and extract the zones map for use as zone_mapping in OPA input.

    Reads the firepilot.yaml file and returns the value of its 'zones' key — a
    mapping of SCM zone names to their metadata objects (role + description).
    This matches the input.zone_mapping structure expected by ADR-0008 policies.

    Args:
        zones_path: Filesystem path to firepilot.yaml.

    Returns:
        Dictionary mapping zone names to zone metadata objects.

    Raises:
        SystemExit: On file not found, YAML parse error, or missing 'zones' key.
    """
    zones_data = load_yaml(zones_path)
    if not isinstance(zones_data, dict) or "zones" not in zones_data:
        print(
            f"Error: {zones_path} must contain a top-level 'zones' key (firepilot.yaml format)",
            file=sys.stderr,
        )
        sys.exit(1)
    return zones_data["zones"]


def build_opa_input(
    directory: Path,
    folder_override: str | None = None,
    position_override: str | None = None,
    config_path: Path | None = None,
) -> dict:
    """Assemble the OPA input object from a folder/position directory.

    Reads _rulebase.yaml as the manifest and all other .yaml files as rule
    files. Derives 'folder' and 'position' from the directory structure
    unless overrides are provided. Optionally includes zone_mapping from
    a firepilot.yaml file to activate topology-aware OPA policies (ADR-0008).

    Args:
        directory: Path to the folder/position directory (e.g. shared/pre/).
        folder_override: If provided, use this as directory.folder instead of
            deriving it from the parent directory name. Useful for invalid
            fixture testing where the fixture path doesn't match the intended
            folder hierarchy.
        position_override: If provided, use this as directory.position instead
            of deriving it from the directory name.
        config_path: If provided, load firepilot.yaml from this path and include
            its 'zones' map as zone_mapping in the OPA input. If None, no
            zone_mapping key is included (backward compatible with configs
            validated before ADR-0008 was introduced).

    Returns:
        OPA input dictionary with 'manifest', 'rule_files', 'directory', and
        optionally 'zone_mapping' keys.

    Raises:
        SystemExit: On missing directory, missing manifest, or parse errors.
    """
    directory = directory.resolve()

    if not directory.is_dir():
        print(f"Error: Not a directory: {directory}", file=sys.stderr)
        sys.exit(1)

    manifest_path = directory / MANIFEST_FILENAME
    if not manifest_path.exists():
        print(
            f"Error: Manifest file not found: {manifest_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Derive folder (parent dir name) and position (current dir name) from
    # the filesystem path — matching the ADR-0007 directory layout convention:
    #   firewall-configs/{folder}/{position}/
    # Overrides allow testing invalid fixtures in isolation by specifying the
    # intended folder/position separately from the fixture's actual path.
    position = position_override if position_override is not None else directory.name
    folder = folder_override if folder_override is not None else directory.parent.name

    manifest = load_yaml(manifest_path)

    # Load all .yaml files except _rulebase.yaml and firepilot.yaml as rule files.
    # Key is the filename without the .yaml extension (matching rule_order entries).
    # firepilot.yaml lives at the repo root (ADR-0012), never inside a rule directory
    # — skip it here regardless to avoid treating it as a rule file when fixture
    # directories colocate it for test convenience.
    rule_files: dict = {}
    for yaml_file in sorted(directory.glob("*.yaml")):
        if yaml_file.name in {MANIFEST_FILENAME, ZONE_MAPPING_FILENAME}:
            continue
        rule_name = yaml_file.stem  # filename without extension
        rule_files[rule_name] = load_yaml(yaml_file)

    opa_input: dict = {
        "manifest": manifest,
        "rule_files": rule_files,
        "directory": {
            "folder": folder,
            "position": position,
        },
    }

    # Include zone_mapping only when --config is supplied. Absence of zone_mapping
    # keeps topology policies dormant, preserving backward compatibility (ADR-0008).
    if config_path is not None:
        opa_input["zone_mapping"] = load_zone_mapping(config_path)

    return opa_input


def main() -> None:
    """Entry point: parse arguments and emit OPA input JSON to stdout."""
    parser = argparse.ArgumentParser(
        description="Assemble OPA input JSON from a firewall-configs directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Exit codes:")[0].strip(),
    )
    parser.add_argument(
        "directory",
        help="Path to the folder/position directory containing _rulebase.yaml",
    )
    parser.add_argument(
        "--folder",
        default=None,
        help=(
            "Override the derived folder name. Default: parent directory name. "
            "Use when testing invalid fixtures that are not in a proper "
            "firewall-configs/{folder}/{position}/ hierarchy."
        ),
    )
    parser.add_argument(
        "--position",
        default=None,
        help=(
            "Override the derived position name. Default: directory name. "
            "Use when testing invalid fixtures that are not in a proper "
            "firewall-configs/{folder}/{position}/ hierarchy."
        ),
    )
    parser.add_argument(
        "--config",
        default=None,
        metavar="CONFIG_FILE",
        help=(
            "Path to firepilot.yaml. When provided, the 'zones' map is included as "
            "'zone_mapping' in the OPA input, activating topology-aware policies "
            "(ADR-0008). When omitted, zone_mapping is absent and topology policies "
            "do not fire — preserving backward compatibility."
        ),
    )

    args = parser.parse_args()
    directory = Path(args.directory)
    config_path = Path(args.config) if args.config is not None else None

    opa_input = build_opa_input(
        directory,
        folder_override=args.folder,
        position_override=args.position,
        config_path=config_path,
    )
    print(json.dumps(opa_input, indent=2))


if __name__ == "__main__":
    main()
