from __future__ import annotations

import json

from python_compat import python_compat_report


def main() -> int:
    report = python_compat_report()
    print(json.dumps(report, indent=2))
    return 0 if report.get("supported") else 2


if __name__ == "__main__":
    raise SystemExit(main())
