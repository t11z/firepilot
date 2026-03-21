"""Regression tests for process_firewall_request.py.

Focused on the PDF attachment parsing logic, including the bug where
`user-attachments/files/` URLs were not recognised (only `assets/` was).
"""

from __future__ import annotations

from process_firewall_request import parse_pdf_attachments


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
