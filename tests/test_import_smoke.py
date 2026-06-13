"""Smoke tests — verify all platform modules import without errors (MRO, syntax, etc.)."""
import importlib
import pytest


@pytest.mark.parametrize("mod", ["binary_sensor", "sensor"])
def test_platform_modules_import(mod):
    """Core platform modules must import cleanly (catches MRO / class-definition errors)."""
    importlib.import_module(f"custom_components.preheat.{mod}")


@pytest.mark.parametrize("mod", ["switch", "button"])
@pytest.mark.xfail(reason="HA mock scaffolding does not cover these platform imports yet", strict=False)
def test_platform_modules_import_optional(mod):
    """Additional platform modules — expected to fail until full HA mock coverage."""
    importlib.import_module(f"custom_components.preheat.{mod}")
