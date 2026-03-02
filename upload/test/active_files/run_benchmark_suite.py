from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from python_compat import require_supported_python


def run_cmd(cmd: list[str]) -> None:
    print(f"[run] {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr)
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(cmd)}")


def main() -> int:
    supported, compat_msg = require_supported_python()
    if not supported:
        print(compat_msg)
        return 2

    default_py = Path(__file__).parent / ".venv" / "Scripts" / "python.exe"
    if not default_py.exists():
        default_py = Path(__file__).parent / ".venv311" / "Scripts" / "python.exe"
    if not default_py.exists():
        default_py = Path(sys.executable)

    parser = argparse.ArgumentParser(description="Run subset benchmark suite (base model, large model, drift eval)")
    parser.add_argument(
        "--python",
        default=str(default_py),
        help="Python executable to use",
    )
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).parent),
        help="Project root containing configs and scripts",
    )
    args = parser.parse_args()

    py = str(Path(args.python))
    root = Path(args.project_root).expanduser().resolve()

    run_pipeline = str(root / "run_pipeline.py")
    eval_drift = str(root / "evaluate_caption_drift.py")

    cfg_base = str(root / "config.caption_subset.yaml")
    cfg_large = str(root / "config.caption_subset_bliplarge.yaml")

    base_csv = str(root / "output_caption_subset" / "records.csv")
    large_csv = str(root / "output_caption_subset_bliplarge" / "records.csv")
    drift_out = str(root / "output_caption_drift_subset")

    run_cmd([py, run_pipeline, "--config", cfg_base])
    run_cmd([py, run_pipeline, "--config", cfg_large])
    run_cmd([
        py,
        eval_drift,
        "--baseline",
        base_csv,
        "--candidate",
        large_csv,
        "--output",
        drift_out,
    ])

    summary_path = Path(drift_out) / "caption_drift_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}

    print(json.dumps({
        "status": "ok",
        "drift_summary": summary,
        "outputs": {
            "base": str(Path(base_csv).parent),
            "candidate": str(Path(large_csv).parent),
            "drift": drift_out,
        },
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
