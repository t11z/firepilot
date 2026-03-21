"""Configuration file output tool for mcp-itsm.

Exposes one tool for writing YAML configuration files to the output directory:
  - write_config_file

Claude calls this tool once per configuration artefact during its agentic loop.
The workflow script detects written files by scanning OUTPUT_DIR for .yaml files.

Both demo and live modes write to the filesystem at OUTPUT_DIR — there is no
fixture-based mock for this tool because the operation is purely local I/O.
The OUTPUT_DIR environment variable must be set by the workflow before the
server is started.

See ADR-0015 for the full design rationale and ADR-0007 for the YAML schema.
"""

import time
from pathlib import Path
from typing import Any

import structlog
import yaml
from mcp.server.fastmcp import FastMCP

from mcp_itsm.config import get_settings

logger = structlog.get_logger(__name__)

# Error codes returned in structured error responses
ERROR_INVALID_FILENAME = "INVALID_FILENAME"
ERROR_INVALID_YAML = "INVALID_YAML"
ERROR_SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
ERROR_NAME_FILENAME_MISMATCH = "NAME_FILENAME_MISMATCH"
ERROR_WRITE_FAILED = "WRITE_FAILED"
ERROR_OUTPUT_DIR_NOT_SET = "OUTPUT_DIR_NOT_SET"

# Valid file_type values
_VALID_FILE_TYPES: frozenset[str] = frozenset(
    {"security_rule", "address_object", "rulebase_manifest"}
)

# Required fields per file_type (ADR-0007)
_REQUIRED_FIELDS: dict[str, list[str]] = {
    "security_rule": ["schema_version", "name", "action"],
    "rulebase_manifest": ["schema_version", "folder", "position", "rule_order"],
}

# The manifest filename that is exempt from name/filename matching (ADR-0007)
_RULEBASE_MANIFEST_FILENAME = "_rulebase.yaml"


def _log_tool_call(
    *,
    tool_name: str,
    mode: str,
    outcome: str,
    duration_ms: int,
    filename: str | None = None,
    file_type: str | None = None,
    file_size: int | None = None,
    rejection_code: str | None = None,
    error_message: str | None = None,
) -> None:
    """Emit a structured log entry for a completed tool invocation.

    Args:
        tool_name: Name of the MCP tool that was called.
        mode: Server mode — "demo" or "live".
        outcome: Result — "success", "failure", or "rejected".
        duration_ms: Wall-clock duration of the tool call in milliseconds.
        filename: Target filename (on success or validation failures).
        file_type: File type parameter passed to the tool.
        file_size: Number of bytes written (on success only).
        rejection_code: Structured error code if outcome is "rejected" or "failure".
        error_message: Human-readable error message if applicable.
    """
    log_fn = logger.info if outcome == "success" else logger.warning
    log_fn(
        "tool_call",
        tool_name=tool_name,
        mode=mode,
        outcome=outcome,
        duration_ms=duration_ms,
        filename=filename,
        file_type=file_type,
        file_size=file_size,
        rejection_code=rejection_code,
        error_message=error_message,
    )


def register_config_file_tools(mcp: FastMCP) -> None:
    """Register all configuration file tools on the provided FastMCP server instance.

    Args:
        mcp: The FastMCP server instance to register tools on.
    """

    @mcp.tool()
    async def write_config_file(
        filename: str,
        content: str,
        file_type: str,
    ) -> dict[str, Any]:
        """Write a YAML configuration file to the output directory for Git commit.

        Validates the filename and content before writing, then writes the raw
        content string to OUTPUT_DIR/{filename}. Both demo and live modes write
        to the local filesystem — the OUTPUT_DIR environment variable must be set.

        Validation order:
          1. filename must end with .yaml
          2. filename must not contain path separators (/, \\) or ..
          3. content must be valid YAML (yaml.safe_load succeeds)
          4. For security_rule: content must contain schema_version, name, action
          5. For rulebase_manifest: content must contain schema_version, folder,
             position, rule_order
          6. For security_rule and rulebase_manifest: the name field (or
             _rulebase.yaml for manifests) must match the filename stem

        Args:
            filename: File name including .yaml extension. For security rules,
                must match the name field in the content. For rulebase manifests,
                use _rulebase.yaml (required).
            content: Complete YAML content of the file, ADR-0007-compliant (required).
            file_type: One of: security_rule, address_object, rulebase_manifest
                (required).

        Returns:
            Dict with file_path (absolute path), file_type (echo of input), and
            file_size (bytes written), or a structured error dict on failure.
        """
        settings = get_settings()
        start = time.monotonic()
        mode = settings.firepilot_env

        # --- Validation 1 & 2: filename safety ---
        if not filename.endswith(".yaml"):
            duration_ms = int((time.monotonic() - start) * 1000)
            _log_tool_call(
                tool_name="write_config_file",
                mode=mode,
                outcome="rejected",
                duration_ms=duration_ms,
                filename=filename,
                file_type=file_type,
                rejection_code=ERROR_INVALID_FILENAME,
                error_message=f"Filename '{filename}' must end with .yaml",
            )
            return {
                "error": {
                    "code": ERROR_INVALID_FILENAME,
                    "message": f"Filename '{filename}' must end with .yaml",
                }
            }

        if "/" in filename or "\\" in filename or ".." in filename:
            duration_ms = int((time.monotonic() - start) * 1000)
            _log_tool_call(
                tool_name="write_config_file",
                mode=mode,
                outcome="rejected",
                duration_ms=duration_ms,
                filename=filename,
                file_type=file_type,
                rejection_code=ERROR_INVALID_FILENAME,
                error_message=(
                    f"Filename '{filename}' must not contain path separators "
                    f"(/, \\) or .."
                ),
            )
            return {
                "error": {
                    "code": ERROR_INVALID_FILENAME,
                    "message": (
                        f"Filename '{filename}' must not contain path separators "
                        f"(/, \\) or .."
                    ),
                }
            }

        # --- Validation 3: YAML parse ---
        try:
            parsed = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            _log_tool_call(
                tool_name="write_config_file",
                mode=mode,
                outcome="rejected",
                duration_ms=duration_ms,
                filename=filename,
                file_type=file_type,
                rejection_code=ERROR_INVALID_YAML,
                error_message=f"Content is not valid YAML: {exc}",
            )
            return {
                "error": {
                    "code": ERROR_INVALID_YAML,
                    "message": f"Content is not valid YAML: {exc}",
                }
            }

        # --- Validation 4 & 5: schema requirements ---
        required_fields = _REQUIRED_FIELDS.get(file_type)
        if required_fields is not None:
            if not isinstance(parsed, dict):
                duration_ms = int((time.monotonic() - start) * 1000)
                _log_tool_call(
                    tool_name="write_config_file",
                    mode=mode,
                    outcome="rejected",
                    duration_ms=duration_ms,
                    filename=filename,
                    file_type=file_type,
                    rejection_code=ERROR_SCHEMA_MISMATCH,
                    error_message=(
                        f"Content for file_type '{file_type}' must be a YAML mapping, "
                        f"got {type(parsed).__name__}"
                    ),
                )
                return {
                    "error": {
                        "code": ERROR_SCHEMA_MISMATCH,
                        "message": (
                            f"Content for file_type '{file_type}' must be a YAML mapping, "
                            f"got {type(parsed).__name__}"
                        ),
                    }
                }

            missing = [f for f in required_fields if f not in parsed]
            if missing:
                duration_ms = int((time.monotonic() - start) * 1000)
                _log_tool_call(
                    tool_name="write_config_file",
                    mode=mode,
                    outcome="rejected",
                    duration_ms=duration_ms,
                    filename=filename,
                    file_type=file_type,
                    rejection_code=ERROR_SCHEMA_MISMATCH,
                    error_message=(
                        f"Content for file_type '{file_type}' is missing required "
                        f"fields: {', '.join(missing)}"
                    ),
                )
                return {
                    "error": {
                        "code": ERROR_SCHEMA_MISMATCH,
                        "message": (
                            f"Content for file_type '{file_type}' is missing required "
                            f"fields: {', '.join(missing)}"
                        ),
                    }
                }

            # --- Validation 6: name/filename consistency ---
            # Rulebase manifests use _rulebase.yaml — exempt from name matching.
            if filename != _RULEBASE_MANIFEST_FILENAME:
                filename_stem = filename[: -len(".yaml")]  # strip .yaml suffix
                if file_type == "security_rule":
                    content_name = str(parsed.get("name", ""))
                    if content_name != filename_stem:
                        duration_ms = int((time.monotonic() - start) * 1000)
                        _log_tool_call(
                            tool_name="write_config_file",
                            mode=mode,
                            outcome="rejected",
                            duration_ms=duration_ms,
                            filename=filename,
                            file_type=file_type,
                            rejection_code=ERROR_NAME_FILENAME_MISMATCH,
                            error_message=(
                                f"The 'name' field in content ('{content_name}') "
                                f"does not match the filename stem ('{filename_stem}')"
                            ),
                        )
                        return {
                            "error": {
                                "code": ERROR_NAME_FILENAME_MISMATCH,
                                "message": (
                                    f"The 'name' field in content ('{content_name}') "
                                    f"does not match the filename stem ('{filename_stem}')"
                                ),
                            }
                        }

        # --- Check OUTPUT_DIR is configured ---
        if not settings.output_dir:
            duration_ms = int((time.monotonic() - start) * 1000)
            _log_tool_call(
                tool_name="write_config_file",
                mode=mode,
                outcome="rejected",
                duration_ms=duration_ms,
                filename=filename,
                file_type=file_type,
                rejection_code=ERROR_OUTPUT_DIR_NOT_SET,
                error_message="OUTPUT_DIR is not configured — cannot write configuration file",
            )
            return {
                "error": {
                    "code": ERROR_OUTPUT_DIR_NOT_SET,
                    "message": "OUTPUT_DIR is not configured — cannot write configuration file",
                }
            }

        # --- Write the file ---
        output_path = Path(settings.output_dir) / filename
        try:
            output_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            _log_tool_call(
                tool_name="write_config_file",
                mode=mode,
                outcome="failure",
                duration_ms=duration_ms,
                filename=filename,
                file_type=file_type,
                rejection_code=ERROR_WRITE_FAILED,
                error_message=f"Failed to write file: {exc}",
            )
            return {
                "error": {
                    "code": ERROR_WRITE_FAILED,
                    "message": f"Failed to write '{filename}': {exc}",
                }
            }

        file_size = output_path.stat().st_size
        duration_ms = int((time.monotonic() - start) * 1000)
        _log_tool_call(
            tool_name="write_config_file",
            mode=mode,
            outcome="success",
            duration_ms=duration_ms,
            filename=filename,
            file_type=file_type,
            file_size=file_size,
        )
        return {
            "file_path": str(output_path.resolve()),
            "file_type": file_type,
            "file_size": file_size,
        }
