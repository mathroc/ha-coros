"""Shared test import machinery.

api.py and models.py are loaded directly via importlib rather than through
`custom_components.coros`'s real __init__.py, since that file imports
Home Assistant (homeassistant.config_entries etc.), which this lightweight
pure-logic test suite deliberately doesn't install - full Home Assistant
integration testing (config_flow, coordinator, sensor) is a separate,
heavier follow-up once there's a real instance to test against.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COROS_DIR = REPO_ROOT / "custom_components" / "coros"


def _load_submodule(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(f"custom_components.coros.{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"custom_components.coros.{name}"] = module
    spec.loader.exec_module(module)
    return module


if "custom_components" not in sys.modules:
    sys.modules["custom_components"] = types.ModuleType("custom_components")

if "custom_components.coros" not in sys.modules:
    stub = types.ModuleType("custom_components.coros")
    stub.__path__ = [str(COROS_DIR)]  # marks it as a package so submodule imports resolve
    sys.modules["custom_components.coros"] = stub

_load_submodule("models", COROS_DIR / "models.py")
_load_submodule("api", COROS_DIR / "api.py")
