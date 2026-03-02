from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from python_compat import require_supported_python


def main() -> int:
    supported, compat_msg = require_supported_python()
    if not supported:
        print(compat_msg)
        return 2

    parser = argparse.ArgumentParser(description="Model promotion policy check")
    parser.add_argument("--baseline", required=True, help="Baseline records.csv")
    parser.add_argument("--candidate", required=True, help="Candidate records.csv")
    parser.add_argument("--max-drift", type=float, default=0.55, help="Maximum acceptable mean drift")
    parser.add_argument("--output", required=True, help="Output decision json path")
    args = parser.parse_args()

    baseline = pd.read_csv(Path(args.baseline).expanduser())
    candidate = pd.read_csv(Path(args.candidate).expanduser())

    bq = float(baseline["caption_quality_score"].mean()) if "caption_quality_score" in baseline.columns and len(baseline) else 0.0
    cq = float(candidate["caption_quality_score"].mean()) if "caption_quality_score" in candidate.columns and len(candidate) else 0.0

    bl = float(baseline["low_quality_flag"].mean()) if "low_quality_flag" in baseline.columns and len(baseline) else 1.0
    cl = float(candidate["low_quality_flag"].mean()) if "low_quality_flag" in candidate.columns and len(candidate) else 1.0

    # optional drift summary neighbor file
    drift_mean = None
    baseline_dir = Path(args.baseline).expanduser().resolve().parent
    candidate_dir = Path(args.candidate).expanduser().resolve().parent
    possible = [
        candidate_dir.parent / "output_caption_drift_subset" / "caption_drift_summary.json",
        baseline_dir.parent / "output_caption_drift_subset" / "caption_drift_summary.json",
    ]
    for p in possible:
        if p.exists():
            try:
                drift_mean = float(json.loads(p.read_text(encoding="utf-8")).get("mean_drift_score"))
                break
            except Exception:
                drift_mean = None

    quality_ok = cq >= bq
    low_quality_ok = cl <= bl
    drift_ok = True if drift_mean is None else (drift_mean <= args.max_drift)

    promote = bool(quality_ok and low_quality_ok and drift_ok)

    decision = {
        "promote_candidate": promote,
        "quality_baseline": round(bq, 4),
        "quality_candidate": round(cq, 4),
        "low_quality_rate_baseline": round(bl, 4),
        "low_quality_rate_candidate": round(cl, 4),
        "mean_drift_score": None if drift_mean is None else round(drift_mean, 4),
        "thresholds": {"max_drift": args.max_drift},
        "checks": {
            "quality_ok": quality_ok,
            "low_quality_ok": low_quality_ok,
            "drift_ok": drift_ok,
        },
    }

    out = Path(args.output).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(decision, indent=2), encoding="utf-8")

    print(json.dumps({"status": "ok", "output": str(out), **decision}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
