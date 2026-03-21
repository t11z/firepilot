"""Tests for write tools: create_security_rule, create_address, create_address_group.

All tests run against demo mode fixtures set in conftest.py.
"""

from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool

# A valid rule creation payload for reuse across tests
VALID_RULE_PAYLOAD = {
    "ticket_id": "CHG0012345",
    "folder": "Shared",
    "position": "pre",
    "name": "allow-test-rule",
    "action": "allow",
    "from_zones": ["web-zone"],
    "to_zones": ["app-zone"],
    "source": ["web-subnet-10.1.0.0-24"],
    "source_user": ["any"],
    "destination": ["app-subnet-10.2.0.0-24"],
    "service": ["application-default"],
    "application": ["ssl"],
    "category": ["any"],
    "description": "Test rule created by automated test",
    "tag": ["firepilot-managed"],
    "log_end": True,
}


class TestCreateSecurityRule:
    """Tests for the create_security_rule tool."""

    async def test_create_security_rule_success(self, server: FastMCP) -> None:
        """Valid input with ticket_id returns a rule with an id field assigned."""
        data = await call_tool(server, "create_security_rule", VALID_RULE_PAYLOAD)
        assert "id" in data
        assert data["id"] == "00000000-0000-0000-0005-000000000001"
        assert "error" not in data

    async def test_create_security_rule_missing_ticket_id(self, server: FastMCP) -> None:
        """Empty ticket_id is rejected with MISSING_TICKET_REF error code."""
        payload = {**VALID_RULE_PAYLOAD, "ticket_id": ""}
        data = await call_tool(server, "create_security_rule", payload)
        assert "error" in data
        assert data["error"]["code"] == "MISSING_TICKET_REF"

    async def test_create_security_rule_whitespace_ticket_id(
        self, server: FastMCP
    ) -> None:
        """Whitespace-only ticket_id is rejected with MISSING_TICKET_REF."""
        payload = {**VALID_RULE_PAYLOAD, "ticket_id": "   "}
        data = await call_tool(server, "create_security_rule", payload)
        assert "error" in data
        assert data["error"]["code"] == "MISSING_TICKET_REF"

    async def test_create_security_rule_echoes_fields(self, server: FastMCP) -> None:
        """All submitted input fields are reflected correctly in the response."""
        data = await call_tool(server, "create_security_rule", VALID_RULE_PAYLOAD)
        assert data["name"] == VALID_RULE_PAYLOAD["name"]
        assert data["action"] == VALID_RULE_PAYLOAD["action"]
        # SCM API uses 'from' and 'to' — not from_zones/to_zones
        assert data["from"] == VALID_RULE_PAYLOAD["from_zones"]
        assert data["to"] == VALID_RULE_PAYLOAD["to_zones"]
        assert data["source"] == VALID_RULE_PAYLOAD["source"]
        assert data["destination"] == VALID_RULE_PAYLOAD["destination"]
        assert data["application"] == VALID_RULE_PAYLOAD["application"]
        assert data["tag"] == VALID_RULE_PAYLOAD["tag"]
        assert data["description"] == VALID_RULE_PAYLOAD["description"]
        assert data["log_end"] == VALID_RULE_PAYLOAD["log_end"]

    async def test_create_security_rule_from_to_field_names(
        self, server: FastMCP
    ) -> None:
        """Response uses SCM API field names 'from'/'to', not Python names."""
        data = await call_tool(server, "create_security_rule", VALID_RULE_PAYLOAD)
        assert "from" in data
        assert "to" in data
        assert "from_zones" not in data
        assert "to_zones" not in data


# Valid address creation payload for reuse across tests
VALID_ADDRESS_PAYLOAD = {
    "ticket_id": "CHG0099001",
    "folder": "Shared",
    "name": "new-web-server-10.5.0.1",
    "description": "New web server",
    "tag": ["firepilot-managed"],
    "ip_netmask": "10.5.0.1/32",
}


class TestCreateAddress:
    """Tests for the create_address tool."""

    async def test_create_address_success(self, server: FastMCP) -> None:
        """Valid input with ticket_id returns an address with an assigned id."""
        data = await call_tool(server, "create_address", VALID_ADDRESS_PAYLOAD)
        assert "id" in data
        assert data["id"] == "00000000-0000-0000-0002-000000000005"
        assert "error" not in data

    async def test_create_address_missing_ticket_id(self, server: FastMCP) -> None:
        """Empty ticket_id is rejected with MISSING_TICKET_REF error code."""
        payload = {**VALID_ADDRESS_PAYLOAD, "ticket_id": ""}
        data = await call_tool(server, "create_address", payload)
        assert "error" in data
        assert data["error"]["code"] == "MISSING_TICKET_REF"

    async def test_create_address_whitespace_ticket_id(self, server: FastMCP) -> None:
        """Whitespace-only ticket_id is rejected with MISSING_TICKET_REF."""
        payload = {**VALID_ADDRESS_PAYLOAD, "ticket_id": "   "}
        data = await call_tool(server, "create_address", payload)
        assert "error" in data
        assert data["error"]["code"] == "MISSING_TICKET_REF"

    async def test_create_address_echoes_fields(self, server: FastMCP) -> None:
        """All submitted input fields are reflected correctly in the response."""
        data = await call_tool(server, "create_address", VALID_ADDRESS_PAYLOAD)
        assert data["name"] == VALID_ADDRESS_PAYLOAD["name"]
        assert data["description"] == VALID_ADDRESS_PAYLOAD["description"]
        assert data["tag"] == VALID_ADDRESS_PAYLOAD["tag"]
        assert data["ip_netmask"] == VALID_ADDRESS_PAYLOAD["ip_netmask"]

    async def test_create_address_visible_in_list(self, server: FastMCP) -> None:
        """Created address appears in subsequent list_addresses call."""
        await call_tool(server, "create_address", VALID_ADDRESS_PAYLOAD)
        list_data = await call_tool(server, "list_addresses", {"folder": "Shared"})
        names = [a["name"] for a in list_data["data"]]
        assert VALID_ADDRESS_PAYLOAD["name"] in names
        assert list_data["total"] == 5  # 4 fixtures + 1 created


# Valid address group creation payload for reuse across tests
VALID_GROUP_PAYLOAD = {
    "ticket_id": "CHG0099002",
    "folder": "Shared",
    "name": "new-group",
    "static": ["web-subnet-10.1.0.0-24", "app-subnet-10.2.0.0-24"],
    "description": "New address group",
    "tag": ["firepilot-managed"],
}


class TestCreateAddressGroup:
    """Tests for the create_address_group tool."""

    async def test_create_address_group_success(self, server: FastMCP) -> None:
        """Valid input with ticket_id returns a group with an assigned id."""
        data = await call_tool(server, "create_address_group", VALID_GROUP_PAYLOAD)
        assert "id" in data
        assert data["id"] == "00000000-0000-0000-0003-000000000002"
        assert "error" not in data

    async def test_create_address_group_missing_ticket_id(
        self, server: FastMCP
    ) -> None:
        """Empty ticket_id is rejected with MISSING_TICKET_REF error code."""
        payload = {**VALID_GROUP_PAYLOAD, "ticket_id": ""}
        data = await call_tool(server, "create_address_group", payload)
        assert "error" in data
        assert data["error"]["code"] == "MISSING_TICKET_REF"

    async def test_create_address_group_whitespace_ticket_id(
        self, server: FastMCP
    ) -> None:
        """Whitespace-only ticket_id is rejected with MISSING_TICKET_REF."""
        payload = {**VALID_GROUP_PAYLOAD, "ticket_id": "   "}
        data = await call_tool(server, "create_address_group", payload)
        assert "error" in data
        assert data["error"]["code"] == "MISSING_TICKET_REF"

    async def test_create_address_group_missing_static(self, server: FastMCP) -> None:
        """Missing static list is rejected with INVALID_INPUT error code."""
        payload = {
            "ticket_id": "CHG0099002",
            "folder": "Shared",
            "name": "empty-group",
        }
        data = await call_tool(server, "create_address_group", payload)
        assert "error" in data
        assert data["error"]["code"] == "INVALID_INPUT"

    async def test_create_address_group_echoes_fields(self, server: FastMCP) -> None:
        """All submitted input fields are reflected correctly in the response."""
        data = await call_tool(server, "create_address_group", VALID_GROUP_PAYLOAD)
        assert data["name"] == VALID_GROUP_PAYLOAD["name"]
        assert data["description"] == VALID_GROUP_PAYLOAD["description"]
        assert data["tag"] == VALID_GROUP_PAYLOAD["tag"]
        assert data["static"] == VALID_GROUP_PAYLOAD["static"]

    async def test_create_address_group_visible_in_list(self, server: FastMCP) -> None:
        """Created group appears in subsequent list_address_groups call."""
        await call_tool(server, "create_address_group", VALID_GROUP_PAYLOAD)
        list_data = await call_tool(
            server, "list_address_groups", {"folder": "Shared"}
        )
        names = [g["name"] for g in list_data["data"]]
        assert VALID_GROUP_PAYLOAD["name"] in names
        assert list_data["total"] == 2  # 1 fixture + 1 created
