from __future__ import annotations

import argparse
import json
from pathlib import Path

from telemetry import export_telemetry_reports
from python_compat import require_supported_python


def main() -> int:
    supported, compat_msg = require_supported_python()
    if not supported:
        print(compat_msg)
        return 2

    parser = argparse.ArgumentParser(description="Export analyzer telemetry in team and AI-crawlable formats")
    parser.add_argument("--runs-root", required=True, help="Folder containing output_* run directories")
    parser.add_argument("--team-output", required=True, help="Output markdown report for human team sharing")
    parser.add_argument("--ai-output", required=True, help="Output JSON report for AI crawling/automation")
    parser.add_argument("--pattern", default="output_*", help="Glob pattern for run directories")
    parser.add_argument("--window-days", type=int, default=30, help="Lookback window in days")
    args = parser.parse_args()

    result = export_telemetry_reports(
        runs_root=Path(args.runs_root),
        team_output_md=Path(args.team_output),
        ai_output_json=Path(args.ai_output),
        pattern=args.pattern,
        day_window=max(1, int(args.window_days)),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
