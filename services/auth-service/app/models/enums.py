from enum import Enum


class UserStatus(str, Enum):
    PENDING_TENANT = "pending_tenant"
    ACTIVE = "active"
    DISABLED = "disabled"
