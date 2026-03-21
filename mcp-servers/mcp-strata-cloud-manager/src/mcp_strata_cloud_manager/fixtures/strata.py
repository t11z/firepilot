"""Demo fixture data representing a small enterprise SCM environment.

All fixtures use deterministic UUIDs for reproducibility and are structurally
identical to what the live SCM API returns. Fixture data represents the
"Shared" folder with a four-tier network segmentation model.

UUID allocation:
  Zones:          00000000-0000-0000-0001-000000000001 to ...0007
  Addresses:      00000000-0000-0000-0002-000000000001 to ...0004
  Address Groups: 00000000-0000-0000-0003-000000000001
  Security Rules: 00000000-0000-0000-0004-000000000001 to ...0003
  Created Rules:  00000000-0000-0000-0005-000000000001 (demo creation)
  Jobs:           00000000-0000-0000-0006-000000000001
"""

FIXTURE_FOLDER = "Shared"

# ---------------------------------------------------------------------------
# Security Zones
# ---------------------------------------------------------------------------

FIXTURE_SECURITY_ZONES: list[dict] = [
    {
        "id": "00000000-0000-0000-0001-000000000001",
        "name": "untrust-zone",
        "folder": "Shared",
        "enable_user_identification": False,
        "enable_device_identification": False,
        "dos_profile": None,
        "dos_log_setting": None,
        "network": [],
        "zone_protection_profile": None,
        "enable_packet_buffer_protection": False,
        "log_setting": None,
        "user_acl": {"include_list": [], "exclude_list": []},
        "device_acl": {"include_list": [], "exclude_list": []},
    },
    {
        "id": "00000000-0000-0000-0001-000000000002",
        "name": "web-zone",
        "folder": "Shared",
        "enable_user_identification": False,
        "enable_device_identification": False,
        "dos_profile": None,
        "dos_log_setting": None,
        "network": [],
        "zone_protection_profile": None,
        "enable_packet_buffer_protection": False,
        "log_setting": None,
        "user_acl": {"include_list": [], "exclude_list": []},
        "device_acl": {"include_list": [], "exclude_list": []},
    },
    {
        "id": "00000000-0000-0000-0001-000000000003",
        "name": "app-zone",
        "folder": "Shared",
        "enable_user_identification": False,
        "enable_device_identification": False,
        "dos_profile": None,
        "dos_log_setting": None,
        "network": [],
        "zone_protection_profile": None,
        "enable_packet_buffer_protection": False,
        "log_setting": None,
        "user_acl": {"include_list": [], "exclude_list": []},
        "device_acl": {"include_list": [], "exclude_list": []},
    },
    {
        "id": "00000000-0000-0000-0001-000000000004",
        "name": "db-zone",
        "folder": "Shared",
        "enable_user_identification": False,
        "enable_device_identification": False,
        "dos_profile": None,
        "dos_log_setting": None,
        "network": [],
        "zone_protection_profile": None,
        "enable_packet_buffer_protection": False,
        "log_setting": None,
        "user_acl": {"include_list": [], "exclude_list": []},
        "device_acl": {"include_list": [], "exclude_list": []},
    },
    {
        "id": "00000000-0000-0000-0001-000000000005",
        "name": "dmz",
        "folder": "Shared",
        "enable_user_identification": False,
        "enable_device_identification": False,
        "dos_profile": None,
        "dos_log_setting": None,
        "network": [],
        "zone_protection_profile": None,
        "enable_packet_buffer_protection": False,
        "log_setting": None,
        "user_acl": {"include_list": [], "exclude_list": []},
        "device_acl": {"include_list": [], "exclude_list": []},
    },
    {
        "id": "00000000-0000-0000-0001-000000000006",
        "name": "trust",
        "folder": "Shared",
        "enable_user_identification": False,
        "enable_device_identification": False,
        "dos_profile": None,
        "dos_log_setting": None,
        "network": [],
        "zone_protection_profile": None,
        "enable_packet_buffer_protection": False,
        "log_setting": None,
        "user_acl": {"include_list": [], "exclude_list": []},
        "device_acl": {"include_list": [], "exclude_list": []},
    },
    {
        "id": "00000000-0000-0000-0001-000000000007",
        "name": "mgmt",
        "folder": "Shared",
        "enable_user_identification": False,
        "enable_device_identification": False,
        "dos_profile": None,
        "dos_log_setting": None,
        "network": [],
        "zone_protection_profile": None,
        "enable_packet_buffer_protection": False,
        "log_setting": None,
        "user_acl": {"include_list": [], "exclude_list": []},
        "device_acl": {"include_list": [], "exclude_list": []},
    },
]

# ---------------------------------------------------------------------------
# Address Objects
# ---------------------------------------------------------------------------

FIXTURE_ADDRESSES: list[dict] = [
    {
        "id": "00000000-0000-0000-0002-000000000001",
        "name": "web-subnet-10.1.0.0-24",
        "description": "Web tier subnet",
        "tag": [],
        "ip_netmask": "10.1.0.0/24",
        "ip_range": None,
        "ip_wildcard": None,
        "fqdn": None,
    },
    {
        "id": "00000000-0000-0000-0002-000000000002",
        "name": "app-subnet-10.2.0.0-24",
        "description": "Application tier subnet",
        "tag": [],
        "ip_netmask": "10.2.0.0/24",
        "ip_range": None,
        "ip_wildcard": None,
        "fqdn": None,
    },
    {
        "id": "00000000-0000-0000-0002-000000000003",
        "name": "db-subnet-10.3.0.0-24",
        "description": "Database tier subnet",
        "tag": [],
        "ip_netmask": "10.3.0.0/24",
        "ip_range": None,
        "ip_wildcard": None,
        "fqdn": None,
    },
    {
        "id": "00000000-0000-0000-0002-000000000004",
        "name": "external-dns-8.8.8.8",
        "description": "Google public DNS",
        "tag": [],
        "ip_netmask": "8.8.8.8/32",
        "ip_range": None,
        "ip_wildcard": None,
        "fqdn": None,
    },
]

# ---------------------------------------------------------------------------
# Address Groups
# ---------------------------------------------------------------------------

FIXTURE_ADDRESS_GROUPS: list[dict] = [
    {
        "id": "00000000-0000-0000-0003-000000000001",
        "name": "internal-subnets",
        "description": "All internal tier subnets",
        "tag": [],
        "static": [
            "web-subnet-10.1.0.0-24",
            "app-subnet-10.2.0.0-24",
            "db-subnet-10.3.0.0-24",
        ],
        "dynamic": None,
    },
]

# ---------------------------------------------------------------------------
# Security Rules (pre-rules in Shared folder)
# ---------------------------------------------------------------------------

FIXTURE_SECURITY_RULES_PRE: list[dict] = [
    {
        "id": "00000000-0000-0000-0004-000000000001",
        "name": "allow-web-to-app",
        "folder": "Shared",
        "policy_type": "Security",
        "disabled": False,
        "description": "Allow web tier to reach application tier",
        "tag": ["firepilot-managed"],
        "from": ["web-zone"],
        "to": ["app-zone"],
        "source": ["web-subnet-10.1.0.0-24"],
        "negate_source": False,
        "source_user": ["any"],
        "destination": ["app-subnet-10.2.0.0-24"],
        "service": ["application-default"],
        "schedule": None,
        "action": "allow",
        "negate_destination": False,
        "source_hip": [],
        "destination_hip": [],
        "application": ["ssl", "web-browsing"],
        "category": ["any"],
        "profile_setting": {"group": []},
        "log_setting": None,
        "log_start": False,
        "log_end": True,
        "tenant_restrictions": [],
    },
    {
        "id": "00000000-0000-0000-0004-000000000002",
        "name": "allow-app-to-db",
        "folder": "Shared",
        "policy_type": "Security",
        "disabled": False,
        "description": "Allow application tier to reach database tier",
        "tag": ["firepilot-managed"],
        "from": ["app-zone"],
        "to": ["db-zone"],
        "source": ["app-subnet-10.2.0.0-24"],
        "negate_source": False,
        "source_user": ["any"],
        "destination": ["db-subnet-10.3.0.0-24"],
        "service": ["application-default"],
        "schedule": None,
        "action": "allow",
        "negate_destination": False,
        "source_hip": [],
        "destination_hip": [],
        "application": ["mysql"],
        "category": ["any"],
        "profile_setting": {"group": []},
        "log_setting": None,
        "log_start": False,
        "log_end": True,
        "tenant_restrictions": [],
    },
    {
        "id": "00000000-0000-0000-0004-000000000003",
        "name": "deny-direct-db-access",
        "folder": "Shared",
        "policy_type": "Security",
        "disabled": False,
        "description": "Block direct access to database tier from untrusted sources",
        "tag": ["firepilot-managed"],
        "from": ["untrust-zone"],
        "to": ["db-zone"],
        "source": ["any"],
        "negate_source": False,
        "source_user": ["any"],
        "destination": ["db-subnet-10.3.0.0-24"],
        "service": ["any"],
        "schedule": None,
        "action": "deny",
        "negate_destination": False,
        "source_hip": [],
        "destination_hip": [],
        "application": ["any"],
        "category": ["any"],
        "profile_setting": {"group": []},
        "log_setting": None,
        "log_start": False,
        "log_end": True,
        "tenant_restrictions": [],
    },
]

FIXTURE_SECURITY_RULES_POST: list[dict] = []

# ---------------------------------------------------------------------------
# Job fixture
# ---------------------------------------------------------------------------

FIXTURE_JOB_TEMPLATE: dict = {
    "device_name": "SCM",
    "type_str": "CommitAndPush",
    "status_str": "FIN",
    "result_str": "OK",
    "percent": "100",
    "summary": "Commit and push completed successfully",
    "description": "FirePilot candidate config push",
    "details": None,
    "uname": "firepilot-service@example.com",
    "start_ts": "2026-03-19T00:00:00.000Z",
    "end_ts": "2026-03-19T00:01:00.000Z",
    "parent_id": "0",
    "job_result": "2",
    "job_status": "FIN",
    "job_type": "CommitAndPush",
}

FIXTURE_JOB_ID = "00000000-0000-0000-0006-000000000001"

# UUID assigned to rules created via create_security_rule in demo mode
FIXTURE_CREATED_RULE_ID = "00000000-0000-0000-0005-000000000001"
