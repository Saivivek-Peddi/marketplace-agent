"""Input validation for tool parameters."""

from __future__ import annotations

MAX_ADDRESS_LENGTH = 200
MAX_ID_LENGTH = 64


class ValidationError(ValueError):
    pass


def validate_address(addr: str, field_name: str = "address") -> str:
    """Validate and clean an address string."""
    if not isinstance(addr, str):
        raise ValidationError(f"{field_name} must be a string")
    addr = addr.strip()
    if not addr:
        raise ValidationError(f"{field_name} cannot be empty")
    if len(addr) < 2:
        raise ValidationError(f"{field_name} is too short")
    if len(addr) > MAX_ADDRESS_LENGTH:
        raise ValidationError(f"{field_name} is too long (max {MAX_ADDRESS_LENGTH} chars)")
    return addr


def validate_id(id_str: str, field_name: str = "ID") -> str:
    """Validate an entity ID string."""
    if not isinstance(id_str, str):
        raise ValidationError(f"{field_name} must be a string")
    id_str = id_str.strip()
    if not id_str:
        raise ValidationError(f"{field_name} cannot be empty")
    if len(id_str) > MAX_ID_LENGTH:
        raise ValidationError(f"{field_name} is too long")
    return id_str
