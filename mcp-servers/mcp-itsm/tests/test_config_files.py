"""Tests for the write_config_file tool.

Covers validation errors, happy paths for all supported file_type values,
OUTPUT_DIR_NOT_SET error, and multiple sequential writes.
"""

from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_SECURITY_RULE_CONTENT = """\
schema_version: 1
name: allow-web-to-app
description: Permit HTTPS from web zone to app zone
from:
  - web-zone
to:
  - app-zone
source:
  - any
source_user:
  - any
destination:
  - any
application:
  - ssl
category:
  - any
service:
  - application-default
action: allow
tag:
  - firepilot-managed
"""

VALID_MANIFEST_CONTENT = """\
schema_version: 1
folder: shared
position: pre
rule_order:
  - allow-web-to-app
"""


# ---------------------------------------------------------------------------
# Happy path — security rule
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_security_rule_happy_path(
    server: FastMCP,
    tmp_path,
    monkeypatch,
) -> None:
    """Valid security rule filename + content writes the file and returns success."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    # Clear lru_cache so Settings picks up the new env var
    from mcp_itsm.config import get_settings
    get_settings.cache_clear()

    result = await call_tool(
        server,
        "write_config_file",
        {
            "filename": "allow-web-to-app.yaml",
            "content": VALID_SECURITY_RULE_CONTENT,
            "file_type": "security_rule",
        },
    )

    assert "error" not in result
    assert result["file_type"] == "security_rule"
    assert result["file_size"] > 0
    assert result["file_path"].endswith("allow-web-to-app.yaml")

    written = tmp_path / "allow-web-to-app.yaml"
    assert written.exists()
    assert written.read_text(encoding="utf-8") == VALID_SECURITY_RULE_CONTENT


# ---------------------------------------------------------------------------
# Happy path — rulebase manifest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_rulebase_manifest_happy_path(
    server: FastMCP,
    tmp_path,
    monkeypatch,
) -> None:
    """_rulebase.yaml with valid manifest content writes the file and returns success."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    from mcp_itsm.config import get_settings
    get_settings.cache_clear()

    result = await call_tool(
        server,
        "write_config_file",
        {
            "filename": "_rulebase.yaml",
            "content": VALID_MANIFEST_CONTENT,
            "file_type": "rulebase_manifest",
        },
    )

    assert "error" not in result
    assert result["file_type"] == "rulebase_manifest"
    assert result["file_size"] > 0

    written = tmp_path / "_rulebase.yaml"
    assert written.exists()
    assert written.read_text(encoding="utf-8") == VALID_MANIFEST_CONTENT


# ---------------------------------------------------------------------------
# Validation: invalid filename — path traversal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_path_traversal_filename_rejected(
    server: FastMCP,
    tmp_path,
    monkeypatch,
) -> None:
    """filename containing .. is rejected with INVALID_FILENAME."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    from mcp_itsm.config import get_settings
    get_settings.cache_clear()

    result = await call_tool(
        server,
        "write_config_file",
        {
            "filename": "../etc/passwd.yaml",
            "content": VALID_SECURITY_RULE_CONTENT,
            "file_type": "security_rule",
        },
    )

    assert result.get("error", {}).get("code") == "INVALID_FILENAME"


# ---------------------------------------------------------------------------
# Validation: invalid filename — no .yaml extension
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_yaml_extension_rejected(
    server: FastMCP,
    tmp_path,
    monkeypatch,
) -> None:
    """filename without .yaml extension is rejected with INVALID_FILENAME."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    from mcp_itsm.config import get_settings
    get_settings.cache_clear()

    result = await call_tool(
        server,
        "write_config_file",
        {
            "filename": "rule.json",
            "content": VALID_SECURITY_RULE_CONTENT,
            "file_type": "security_rule",
        },
    )

    assert result.get("error", {}).get("code") == "INVALID_FILENAME"


# ---------------------------------------------------------------------------
# Validation: invalid YAML content
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invalid_yaml_content_rejected(
    server: FastMCP,
    tmp_path,
    monkeypatch,
) -> None:
    """Content that cannot be parsed as YAML is rejected with INVALID_YAML."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    from mcp_itsm.config import get_settings
    get_settings.cache_clear()

    result = await call_tool(
        server,
        "write_config_file",
        {
            "filename": "allow-web-to-app.yaml",
            # Unclosed brace causes a YAML scanner error
            "content": "key: {unclosed bracket",
            "file_type": "security_rule",
        },
    )

    assert result.get("error", {}).get("code") == "INVALID_YAML"


# ---------------------------------------------------------------------------
# Validation: schema mismatch — security_rule missing 'action'
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_security_rule_missing_action_rejected(
    server: FastMCP,
    tmp_path,
    monkeypatch,
) -> None:
    """security_rule content missing the 'action' field is rejected with SCHEMA_MISMATCH."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    from mcp_itsm.config import get_settings
    get_settings.cache_clear()

    content_missing_action = """\
schema_version: 1
name: allow-web-to-app
from:
  - web-zone
to:
  - app-zone
"""
    result = await call_tool(
        server,
        "write_config_file",
        {
            "filename": "allow-web-to-app.yaml",
            "content": content_missing_action,
            "file_type": "security_rule",
        },
    )

    assert result.get("error", {}).get("code") == "SCHEMA_MISMATCH"


# ---------------------------------------------------------------------------
# Validation: name/filename mismatch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_name_filename_mismatch_rejected(
    server: FastMCP,
    tmp_path,
    monkeypatch,
) -> None:
    """'name' field in content that doesn't match filename stem is rejected."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    from mcp_itsm.config import get_settings
    get_settings.cache_clear()

    content_wrong_name = """\
schema_version: 1
name: bar
action: allow
"""
    result = await call_tool(
        server,
        "write_config_file",
        {
            "filename": "foo.yaml",
            "content": content_wrong_name,
            "file_type": "security_rule",
        },
    )

    assert result.get("error", {}).get("code") == "NAME_FILENAME_MISMATCH"


# ---------------------------------------------------------------------------
# Validation: OUTPUT_DIR not set
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_output_dir_not_set_rejected(
    server: FastMCP,
    monkeypatch,
) -> None:
    """Missing OUTPUT_DIR returns OUTPUT_DIR_NOT_SET error."""
    monkeypatch.delenv("OUTPUT_DIR", raising=False)
    from mcp_itsm.config import get_settings
    get_settings.cache_clear()

    result = await call_tool(
        server,
        "write_config_file",
        {
            "filename": "allow-web-to-app.yaml",
            "content": VALID_SECURITY_RULE_CONTENT,
            "file_type": "security_rule",
        },
    )

    assert result.get("error", {}).get("code") == "OUTPUT_DIR_NOT_SET"


# ---------------------------------------------------------------------------
# Multiple writes — both files exist in output directory
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multiple_writes_both_files_exist(
    server: FastMCP,
    tmp_path,
    monkeypatch,
) -> None:
    """Calling write_config_file twice with different filenames writes both files."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    from mcp_itsm.config import get_settings
    get_settings.cache_clear()

    second_rule_content = """\
schema_version: 1
name: deny-direct-db-access
from:
  - web-zone
to:
  - db-zone
source:
  - any
source_user:
  - any
destination:
  - any
application:
  - any
category:
  - any
service:
  - application-default
action: deny
tag:
  - firepilot-managed
"""

    result1 = await call_tool(
        server,
        "write_config_file",
        {
            "filename": "allow-web-to-app.yaml",
            "content": VALID_SECURITY_RULE_CONTENT,
            "file_type": "security_rule",
        },
    )
    result2 = await call_tool(
        server,
        "write_config_file",
        {
            "filename": "deny-direct-db-access.yaml",
            "content": second_rule_content,
            "file_type": "security_rule",
        },
    )

    assert "error" not in result1
    assert "error" not in result2

    assert (tmp_path / "allow-web-to-app.yaml").exists()
    assert (tmp_path / "deny-direct-db-access.yaml").exists()
