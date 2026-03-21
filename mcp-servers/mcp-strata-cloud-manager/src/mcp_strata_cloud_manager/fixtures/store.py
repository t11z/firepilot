"""Mutable session store for SCM demo mode fixtures.

Initialises from static fixture data on first use. Write tools append to it.
Read tools query it. Singleton per process.

UUID allocation for demo-created objects:
  Created Addresses:      00000000-0000-0000-0002-000000000005+
  Created Address Groups: 00000000-0000-0000-0003-000000000002+
  Created Rules:          00000000-0000-0000-0005-000000000001+
"""

from typing import Any

from mcp_strata_cloud_manager.fixtures.strata import (
    FIXTURE_ADDRESS_GROUPS,
    FIXTURE_ADDRESSES,
    FIXTURE_SECURITY_RULES_POST,
    FIXTURE_SECURITY_RULES_PRE,
)

# Counter start positions — set after the last statically-defined fixture of each type.
_ADDR_COUNTER_START: int = 5  # 4 existing address fixtures; next is 000000000005
_GROUP_COUNTER_START: int = 2  # 1 existing group fixture; next is 000000000002
_RULE_COUNTER_START: int = 1  # First created rule demo UUID


class SCMFixtureStore:
    """Mutable session store for demo mode.

    Initialises from static fixture data. Write tools append to it.
    Read tools query it. Singleton per process.

    Call reset() between test cases to restore the initial fixture state.
    """

    def __init__(self) -> None:
        """Initialise store from static fixture data."""
        self._reset_state()

    def _reset_state(self) -> None:
        """Populate all collections from the static fixture lists."""
        self._addresses: list[dict[str, Any]] = list(FIXTURE_ADDRESSES)
        self._address_groups: list[dict[str, Any]] = list(FIXTURE_ADDRESS_GROUPS)
        self._security_rules_pre: list[dict[str, Any]] = list(FIXTURE_SECURITY_RULES_PRE)
        self._security_rules_post: list[dict[str, Any]] = list(
            FIXTURE_SECURITY_RULES_POST
        )
        self._address_counter: int = _ADDR_COUNTER_START
        self._group_counter: int = _GROUP_COUNTER_START
        self._rule_counter: int = _RULE_COUNTER_START

    def reset(self) -> None:
        """Reset store to initial fixture state.

        Intended for use between test runs to ensure test isolation.
        """
        self._reset_state()

    def get_addresses(self) -> list[dict[str, Any]]:
        """Return the current address list, including session-created entries."""
        return self._addresses

    def get_address_groups(self) -> list[dict[str, Any]]:
        """Return the current address group list, including session-created entries."""
        return self._address_groups

    def get_security_rules(self, position: str) -> list[dict[str, Any]]:
        """Return security rules for the given position.

        Args:
            position: Rule position — 'pre' or 'post'.

        Returns:
            List of security rule dicts including session-created entries.
        """
        return (
            self._security_rules_pre if position == "pre" else self._security_rules_post
        )

    def add_address(self, address_data: dict[str, Any]) -> dict[str, Any]:
        """Add an address to the session store and return it with an assigned UUID.

        UUID pattern: 00000000-0000-0000-0002-{counter:012d}

        Args:
            address_data: Address fields without an id key.

        Returns:
            Address dict with the assigned id prepended.
        """
        uuid = f"00000000-0000-0000-0002-{self._address_counter:012d}"
        self._address_counter += 1
        entry: dict[str, Any] = {"id": uuid, **address_data}
        self._addresses.append(entry)
        return entry

    def add_address_group(self, group_data: dict[str, Any]) -> dict[str, Any]:
        """Add an address group to the session store and return it with an assigned UUID.

        UUID pattern: 00000000-0000-0000-0003-{counter:012d}

        Args:
            group_data: Address group fields without an id key.

        Returns:
            Address group dict with the assigned id prepended.
        """
        uuid = f"00000000-0000-0000-0003-{self._group_counter:012d}"
        self._group_counter += 1
        entry: dict[str, Any] = {"id": uuid, **group_data}
        self._address_groups.append(entry)
        return entry

    def add_security_rule(
        self, rule_data: dict[str, Any], position: str
    ) -> dict[str, Any]:
        """Add a security rule to the session store and return it with an assigned UUID.

        UUID pattern: 00000000-0000-0000-0005-{counter:012d}

        Args:
            rule_data: Security rule fields without an id key.
            position: Rule position — 'pre' or 'post'.

        Returns:
            Security rule dict with the assigned id prepended.
        """
        uuid = f"00000000-0000-0000-0005-{self._rule_counter:012d}"
        self._rule_counter += 1
        entry: dict[str, Any] = {"id": uuid, **rule_data}
        if position == "pre":
            self._security_rules_pre.append(entry)
        else:
            self._security_rules_post.append(entry)
        return entry


_store = SCMFixtureStore()


def get_fixture_store() -> SCMFixtureStore:
    """Return the module-level fixture store singleton.

    Returns:
        The shared SCMFixtureStore instance.
    """
    return _store
