"""Tests for operations tools: push_candidate_config, get_job_status.

All tests run against demo mode fixtures set in conftest.py.
"""

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool


class TestPushCandidateConfig:
    """Tests for the push_candidate_config tool."""

    async def test_push_candidate_config_success(self, server: FastMCP) -> None:
        """Valid input returns a completed push with status_str 'FIN' and result_str 'OK'."""
        data = await call_tool(
            server,
            "push_candidate_config",
            {
                "ticket_id": "CHG0012345",
                "folders": ["Shared"],
                "description": "Test push",
            },
        )
        assert data["status_str"] == "FIN"
        assert data["result_str"] == "OK"
        assert "job_id" in data
        assert "error" not in data

    async def test_push_candidate_config_missing_ticket_id(
        self, server: FastMCP
    ) -> None:
        """Empty ticket_id is rejected with MISSING_TICKET_REF error code."""
        data = await call_tool(
            server,
            "push_candidate_config",
            {"ticket_id": "", "folders": ["Shared"]},
        )
        assert "error" in data
        assert data["error"]["code"] == "MISSING_TICKET_REF"

    async def test_push_candidate_config_returns_job_id(
        self, server: FastMCP
    ) -> None:
        """Successful push returns a non-empty job_id."""
        data = await call_tool(
            server,
            "push_candidate_config",
            {"ticket_id": "CHG0012345", "folders": ["Shared"]},
        )
        assert data["job_id"]
        assert isinstance(data["job_id"], str)


class TestGetJobStatus:
    """Tests for the get_job_status tool."""

    async def test_get_job_status_returns_job(self, server: FastMCP) -> None:
        """Response contains a data list with a job matching the requested job_id."""
        job_id = "test-job-id-12345"
        data = await call_tool(server, "get_job_status", {"job_id": job_id})
        assert "data" in data
        assert len(data["data"]) == 1
        assert data["data"][0]["id"] == job_id

    async def test_get_job_status_completed_job(self, server: FastMCP) -> None:
        """Demo fixture always returns a completed job (status_str FIN, result_str OK)."""
        data = await call_tool(
            server, "get_job_status", {"job_id": "00000000-0000-0000-0006-000000000001"}
        )
        job = data["data"][0]
        assert job["status_str"] == "FIN"
        assert job["result_str"] == "OK"

    async def test_get_job_status_job_fields_present(self, server: FastMCP) -> None:
        """Returned Job object includes all required SCM API fields."""
        data = await call_tool(
            server, "get_job_status", {"job_id": "some-job-id"}
        )
        job = data["data"][0]
        required_fields = (
            "id", "device_name", "type_str", "status_str", "result_str",
            "percent", "summary", "uname", "start_ts", "end_ts",
            "parent_id", "job_result", "job_status", "job_type",
        )
        for field in required_fields:
            assert field in job, f"Missing required Job field: {field}"
