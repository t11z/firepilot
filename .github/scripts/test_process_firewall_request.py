"""Tests for process_firewall_request.py.

Covers:
  - PDF attachment parsing (parse_pdf_attachments)
  - Output directory scanning (scan_output_directory)
  - Metadata extraction from config files (extract_metadata_from_files)
"""

from __future__ import annotations

from pathlib import Path

from process_firewall_request import (
    extract_metadata_from_files,
    parse_pdf_attachments,
    scan_output_directory,
)


# ---------------------------------------------------------------------------
# parse_pdf_attachments — URL pattern coverage
# ---------------------------------------------------------------------------

class TestParsePdfAttachments:
    """Tests for parse_pdf_attachments()."""

    def test_assets_url_is_matched(self) -> None:
        """Current GitHub asset pipeline URL is recognised."""
        body = (
            "See attached:\n"
            "[manual.pdf](https://github.com/user-attachments/assets/abc-123-def)"
        )
        result = parse_pdf_attachments(body)
        assert result == [("manual.pdf", "https://github.com/user-attachments/assets/abc-123-def")]

    def test_files_url_is_matched(self) -> None:
        """Legacy GitHub files URL is recognised (regression for the original bug)."""
        body = (
            "### Supporting Documentation\n"
            "[pigeon-track-manual.pdf]"
            "(https://github.com/user-attachments/files/26156439/pigeon-track-manual.pdf)"
        )
        result = parse_pdf_attachments(body)
        assert result == [
            (
                "pigeon-track-manual.pdf",
                "https://github.com/user-attachments/files/26156439/pigeon-track-manual.pdf",
            )
        ]

    def test_no_attachments_returns_empty_list(self) -> None:
        """Issue body with no PDF links returns empty list."""
        body = "No attachments here, just plain text."
        assert parse_pdf_attachments(body) == []

    def test_non_pdf_attachment_is_ignored(self) -> None:
        """Non-PDF file links are not included in results."""
        body = "[diagram.png](https://github.com/user-attachments/assets/some-uuid)"
        assert parse_pdf_attachments(body) == []

    def test_multiple_pdfs_all_returned(self) -> None:
        """Multiple PDF attachments (mixed URL styles) are all returned."""
        body = (
            "[a.pdf](https://github.com/user-attachments/assets/uuid-1)\n"
            "[b.pdf](https://github.com/user-attachments/files/99999/b.pdf)"
        )
        result = parse_pdf_attachments(body)
        assert len(result) == 2
        filenames = [name for name, _ in result]
        assert "a.pdf" in filenames
        assert "b.pdf" in filenames

    def test_case_insensitive_extension(self) -> None:
        """Uppercase .PDF extension is matched."""
        body = "[REPORT.PDF](https://github.com/user-attachments/files/12345/REPORT.PDF)"
        result = parse_pdf_attachments(body)
        assert len(result) == 1
        assert result[0][0] == "REPORT.PDF"

    def test_unrecognised_host_is_ignored(self) -> None:
        """URLs from other hosts are not matched."""
        body = "[evil.pdf](https://evil.example.com/user-attachments/files/1/evil.pdf)"
        assert parse_pdf_attachments(body) == []


# ---------------------------------------------------------------------------
# scan_output_directory — directory scanning (ADR-0015)
# ---------------------------------------------------------------------------

class TestScanOutputDirectory:
    """Tests for scan_output_directory()."""

    def test_empty_directory_returns_empty_list(self, tmp_path: Path) -> None:
        """An output directory with no .yaml files returns an empty list."""
        assert scan_output_directory(tmp_path) == []

    def test_yaml_files_are_returned(self, tmp_path: Path) -> None:
        """All .yaml files in the directory are returned."""
        (tmp_path / "allow-web-to-app.yaml").write_text("schema_version: 1\n")
        (tmp_path / "_rulebase.yaml").write_text("schema_version: 1\n")

        result = scan_output_directory(tmp_path)
        names = [p.name for p in result]
        assert "_rulebase.yaml" in names
        assert "allow-web-to-app.yaml" in names

    def test_non_yaml_files_are_excluded(self, tmp_path: Path) -> None:
        """Non-.yaml files in the output directory are not returned."""
        (tmp_path / "rule.json").write_text("{}")
        (tmp_path / "notes.txt").write_text("notes")
        (tmp_path / "allow-web.yaml").write_text("schema_version: 1\n")

        result = scan_output_directory(tmp_path)
        assert len(result) == 1
        assert result[0].name == "allow-web.yaml"

    def test_results_are_sorted_by_name(self, tmp_path: Path) -> None:
        """Returned paths are sorted alphabetically by filename."""
        (tmp_path / "zzz-last.yaml").write_text("schema_version: 1\n")
        (tmp_path / "aaa-first.yaml").write_text("schema_version: 1\n")
        (tmp_path / "_rulebase.yaml").write_text("schema_version: 1\n")

        result = scan_output_directory(tmp_path)
        names = [p.name for p in result]
        assert names == sorted(names)

    def test_presence_indicates_proposal(self, tmp_path: Path) -> None:
        """Presence of files → truthy result (proposal exists)."""
        (tmp_path / "allow-web.yaml").write_text("schema_version: 1\n")
        assert bool(scan_output_directory(tmp_path)) is True

    def test_absence_indicates_rejection(self, tmp_path: Path) -> None:
        """Absence of files → falsy result (rejection)."""
        assert bool(scan_output_directory(tmp_path)) is False


# ---------------------------------------------------------------------------
# extract_metadata_from_files — metadata extraction
# ---------------------------------------------------------------------------

SECURITY_RULE_YAML = """\
schema_version: 1
name: allow-web-to-app
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

MANIFEST_YAML = """\
schema_version: 1
folder: shared
position: pre
rule_order:
  - allow-web-to-app
"""


class TestExtractMetadataFromFiles:
    """Tests for extract_metadata_from_files()."""

    def test_extracts_from_security_rule_only(self, tmp_path: Path) -> None:
        """Metadata is correctly extracted from a single security rule file."""
        rule_file = tmp_path / "allow-web-to-app.yaml"
        rule_file.write_text(SECURITY_RULE_YAML)

        result = extract_metadata_from_files([rule_file])

        assert result["rule_name"] == "allow-web-to-app"
        assert result["action"] == "allow"
        assert "web-zone" in result["from_zones"]
        assert "app-zone" in result["to_zones"]
        assert "application-default" in result["services"]

    def test_extracts_folder_and_position_from_manifest(self, tmp_path: Path) -> None:
        """folder and position are read from _rulebase.yaml when present."""
        rule_file = tmp_path / "allow-web-to-app.yaml"
        rule_file.write_text(SECURITY_RULE_YAML)
        manifest_file = tmp_path / "_rulebase.yaml"
        manifest_file.write_text(MANIFEST_YAML)

        result = extract_metadata_from_files([manifest_file, rule_file])

        assert result["folder"] == "shared"
        assert result["position"] == "pre"

    def test_uses_defaults_when_manifest_absent(self, tmp_path: Path) -> None:
        """When no _rulebase.yaml is present, folder and position fall back to defaults."""
        rule_file = tmp_path / "allow-web-to-app.yaml"
        rule_file.write_text(SECURITY_RULE_YAML)

        result = extract_metadata_from_files([rule_file])

        assert result["folder"] == "shared"
        assert result["position"] == "pre"

    def test_rule_name_from_manifest_rule_order(self, tmp_path: Path) -> None:
        """rule_name is derived from the first entry in _rulebase.yaml rule_order."""
        rule_file = tmp_path / "allow-web-to-app.yaml"
        rule_file.write_text(SECURITY_RULE_YAML)
        manifest_file = tmp_path / "_rulebase.yaml"
        manifest_file.write_text(MANIFEST_YAML)

        result = extract_metadata_from_files([manifest_file, rule_file])

        assert result["rule_name"] == "allow-web-to-app"

    def test_multiple_rule_files_aggregate_zones(self, tmp_path: Path) -> None:
        """from_zones and to_zones are aggregated across multiple rule files."""
        rule1 = tmp_path / "allow-web-to-app.yaml"
        rule1.write_text(SECURITY_RULE_YAML)

        rule2_content = """\
schema_version: 1
name: allow-app-to-db
from:
  - app-zone
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
  - tcp-3306
action: allow
tag:
  - firepilot-managed
"""
        rule2 = tmp_path / "allow-app-to-db.yaml"
        rule2.write_text(rule2_content)

        result = extract_metadata_from_files([rule1, rule2])

        assert "web-zone" in result["from_zones"]
        assert "app-zone" in result["from_zones"]
        assert "app-zone" in result["to_zones"]
        assert "db-zone" in result["to_zones"]
