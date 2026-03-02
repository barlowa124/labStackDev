from __future__ import annotations

import argparse
import json
from pathlib import Path

from lab_ops import weekly_summary
from python_compat import require_supported_python


def main() -> int:
    supported, compat_msg = require_supported_python()
    if not supported:
        print(compat_msg)
        return 2

    parser = argparse.ArgumentParser(description="Generate weekly PI summary from run output folders")
    parser.add_argument("--runs-root", required=True, help="Folder containing run output directories")
    parser.add_argument("--pattern", default="output_*", help="Glob pattern for run folders")
    parser.add_argument("--output", required=True, help="Output markdown file path")
    args = parser.parse_args()

    root = Path(args.runs_root).expanduser().resolve()
    run_dirs = [p for p in root.glob(args.pattern) if p.is_dir()]
    summary = weekly_summary(run_dirs)

    out_path = Path(args.output).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if summary.get("status") != "ok":
        out_path.write_text("# Weekly PI Summary\n\nNo valid runs found.", encoding="utf-8")
        print(json.dumps({"status": "no-runs", "output": str(out_path)}, indent=2))
        return 0

    lines = [
        "# Weekly PI Summary",
        "",
        f"- Run count: {summary['run_count']}",
        f"- Total processed images: {summary['total_processed']}",
        f"- Total failed images: {summary['total_failed']}",
        f"- Median caption quality across runs: {summary['median_quality_across_runs']}",
        f"- Mean low-quality rate: {summary['mean_low_quality_rate']}",
        "",
        "## Runs",
        "",
    ]

    for run in summary.get("runs", []):
        lines.append(
            f"- `{run['run_dir']}` | processed={run['processed_count']} | failed={run['failed_count']} | "
            f"median_quality={round(run['median_caption_quality'],4)} | low_quality_rate={round(run['low_quality_rate'],4)} | "
            f"status={run['run_status_light']}"
        )

    out_path.write_text("\n".join(lines), encoding="utf-8")

    json_out = out_path.with_suffix(".json")
    json_out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps({"status": "ok", "output_md": str(out_path), "output_json": str(json_out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
