from __future__ import annotations

import sys
from typing import Any


SUPPORTED_MIN = (3, 10)
SUPPORTED_MAX = (3, 14)


def _version_tuple() -> tuple[int, int, int]:
    return (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)


def _version_text(v: tuple[int, int, int]) -> str:
    return f"{v[0]}.{v[1]}.{v[2]}"


def _supported_range_text() -> str:
    return f"{SUPPORTED_MIN[0]}.{SUPPORTED_MIN[1]} to {SUPPORTED_MAX[0]}.{SUPPORTED_MAX[1]}"


def python_compat_report() -> dict[str, Any]:
    current = _version_tuple()
    current_mm = current[:2]
    supported = SUPPORTED_MIN <= current_mm <= SUPPORTED_MAX

    if supported:
        message = f"Python {_version_text(current)} is supported (range {_supported_range_text()})."
    elif current_mm < SUPPORTED_MIN:
        message = (
            f"Python {_version_text(current)} is too old. "
            f"Use Python {_supported_range_text()} for this project."
        )
    else:
        message = (
            f"Python {_version_text(current)} is newer than validated range. "
            f"Use Python {_supported_range_text()} for best compatibility."
        )

    return {
        "supported": supported,
        "python_version": _version_text(current),
        "supported_range": _supported_range_text(),
        "message": message,
    }


def require_supported_python() -> tuple[bool, str]:
    report = python_compat_report()
    return bool(report["supported"]), str(report["message"])
