"""Pydantic models for SCM API response types.

Field names match the official Palo Alto Networks SCM API exactly.
The SecurityRule model uses Pydantic field aliases for the reserved Python
keywords 'from' and 'to' (serialized as 'from' and 'to' in JSON output).
"""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class UserAcl(BaseModel):
    """User access control list configuration for a security zone."""

    include_list: list[str] = Field(default_factory=list)
    exclude_list: list[str] = Field(default_factory=list)


class DeviceAcl(BaseModel):
    """Device access control list configuration for a security zone."""

    include_list: list[str] = Field(default_factory=list)
    exclude_list: list[str] = Field(default_factory=list)


class ProfileSetting(BaseModel):
    """Security profile group setting for a security rule."""

    group: list[str] = Field(default_factory=list)


class SecurityRule(BaseModel):
    """SCM Security Rule object.

    Uses populate_by_name=True so that both the Python field names (from_, to_)
    and the JSON aliases ('from', 'to') can be used when constructing instances.
    Serialize with model_dump(by_alias=True) to produce correct JSON output.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    folder: str
    policy_type: str = "Security"
    disabled: bool = False
    description: str | None = None
    tag: list[str] = Field(default_factory=list)
    from_: list[str] = Field(alias="from", default_factory=list)
    to_: list[str] = Field(alias="to", default_factory=list)
    source: list[str] = Field(default_factory=list)
    negate_source: bool = False
    source_user: list[str] = Field(default_factory=list)
    destination: list[str] = Field(default_factory=list)
    service: list[str] = Field(default_factory=list)
    schedule: str | None = None
    action: str = "allow"
    negate_destination: bool = False
    source_hip: list[str] = Field(default_factory=list)
    destination_hip: list[str] = Field(default_factory=list)
    application: list[str] = Field(default_factory=list)
    category: list[str] = Field(default_factory=list)
    profile_setting: ProfileSetting | None = None
    log_setting: str | None = None
    log_start: bool = False
    log_end: bool = True
    tenant_restrictions: list[str] = Field(default_factory=list)


class SecurityZone(BaseModel):
    """SCM Security Zone object."""

    id: str
    name: str
    folder: str
    enable_user_identification: bool = False
    enable_device_identification: bool = False
    dos_profile: str | None = None
    dos_log_setting: str | None = None
    network: list[str] = Field(default_factory=list)
    zone_protection_profile: str | None = None
    enable_packet_buffer_protection: bool = False
    log_setting: str | None = None
    user_acl: UserAcl = Field(default_factory=UserAcl)
    device_acl: DeviceAcl = Field(default_factory=DeviceAcl)


class AddressObject(BaseModel):
    """SCM Address Object.

    Exactly one of ip_netmask, ip_range, ip_wildcard, or fqdn should be set.
    """

    id: str
    name: str
    description: str | None = None
    tag: list[str] = Field(default_factory=list)
    ip_netmask: str | None = None
    ip_range: str | None = None
    ip_wildcard: str | None = None
    fqdn: str | None = None


class AddressGroup(BaseModel):
    """SCM Address Group object.

    Either static (list of member address object names) or dynamic
    (filter expression object) should be set.
    """

    id: str
    name: str
    description: str | None = None
    tag: list[str] = Field(default_factory=list)
    static: list[str] | None = None
    dynamic: dict[str, Any] | None = None  # Dynamic filter expression; shape varies per SCM API


class Job(BaseModel):
    """SCM Job object returned by the operations API."""

    id: str
    device_name: str
    type_str: str
    status_str: str
    result_str: str
    percent: str
    summary: str
    description: str | None = None
    details: str | None = None
    uname: str
    start_ts: str
    end_ts: str
    parent_id: str
    job_result: str
    job_status: str
    job_type: str


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper matching SCM API list responses."""

    data: list[T]
    limit: int
    offset: int
    total: int
