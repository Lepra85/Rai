"""Canonical role enum. Single source of truth shared by models and catalog."""
from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    """Roles a user can hold within a business (empresa)."""

    DUEÑO = "dueño"
    ENCARGADO = "encargado"
    EMPLEADO = "empleado"


ALL_ROLES: frozenset[Role] = frozenset(Role)
