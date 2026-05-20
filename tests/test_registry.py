"""
Tests for :mod:`core.registry`.
"""

from __future__ import annotations

import pytest

from core.exceptions import RegistryError
from core.registry import ServiceRegistry


class _Marker:
    pass


def test_register_and_get_by_type() -> None:
    reg = ServiceRegistry()
    obj = _Marker()
    reg.register(_Marker, obj)
    assert reg.get(_Marker) is obj
    assert _Marker in reg
    assert len(reg) == 1


def test_register_and_get_by_string() -> None:
    reg = ServiceRegistry()
    reg.register("vault", {"x": 1})
    assert reg.get("vault") == {"x": 1}
    assert reg.has("vault")


def test_duplicate_registration_raises() -> None:
    reg = ServiceRegistry()
    reg.register("k", 1)
    with pytest.raises(RegistryError):
        reg.register("k", 2)


def test_replace_flag_overrides() -> None:
    reg = ServiceRegistry()
    reg.register("k", 1)
    reg.register("k", 2, replace=True)
    assert reg.get("k") == 2


def test_missing_get_raises_with_helpful_message() -> None:
    reg = ServiceRegistry()
    reg.register("alpha", 1)
    with pytest.raises(RegistryError, match="alpha"):
        reg.get("missing")


def test_unregister_and_clear() -> None:
    reg = ServiceRegistry()
    reg.register("a", 1)
    reg.register("b", 2)
    reg.unregister("a")
    assert not reg.has("a") and reg.has("b")
    reg.clear()
    assert len(reg) == 0
