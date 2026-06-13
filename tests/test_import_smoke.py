"""Smoke tests — verify all platform modules import without errors (MRO, syntax, etc.)."""
import importlib
import pytest


@pytest.mark.parametrize("mod", ["binary_sensor", "sensor", "switch", "button"])
def test_platform_modules_import(mod):
    """Platform modules must import cleanly (catches MRO / class-definition errors)."""
    importlib.import_module(f"custom_components.preheat.{mod}")
