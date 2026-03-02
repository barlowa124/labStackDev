from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List

import pandas as pd

from python_compat import require_supported_python


def _token_set(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z]+", (text or "").lower()))


def _jaccard(a: str, b: str) -> float:
    sa = _token_set(a)
    sb = _token_set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _safe(v: object) -> str:
    if v is None:
        return ""
    s = str(v)
    return "" if s == "nan" else s


def main() -> int:
    supported, compat_msg = require_supported_python()
    if not supported:
        print(compat_msg)
        return 2

    parser = argparse.ArgumentParser(description="Compare caption drift between two runs/models")
    parser.add_argument("--baseline", required=True, help="Path to baseline records.csv")
    parser.add_argument("--candidate", required=True, help="Path to candidate records.csv")
    parser.add_argument("--output", required=True, help="Output directory for drift report")
    parser.add_argument("--caption-column", default="model_caption_microscopy_safe", help="Caption column to compare")
    args = parser.parse_args()

    baseline_path = Path(args.baseline).expanduser()
    candidate_path = Path(args.candidate).expanduser()
    out_dir = Path(args.output).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    base = pd.read_csv(baseline_path)
    cand = pd.read_csv(candidate_path)

    col = args.caption_column
    if col not in base.columns:
        raise ValueError(f"Column not found in baseline: {col}")
    if col not in cand.columns:
        raise ValueError(f"Column not found in candidate: {col}")

    base = base[["image_path", col] + (["caption_quality_score"] if "caption_quality_score" in base.columns else [])].copy()
    cand = cand[["image_path", col] + (["caption_quality_score"] if "caption_quality_score" in cand.columns else [])].copy()

    base = base.rename(columns={col: "baseline_caption", "caption_quality_score": "baseline_quality_score"})
    cand = cand.rename(columns={col: "candidate_caption", "caption_quality_score": "candidate_quality_score"})

    merged = pd.merge(base, cand, on="image_path", how="inner")

    rows: List[Dict] = []
    for _, r in merged.iterrows():
        b = _safe(r.get("baseline_caption"))
        c = _safe(r.get("candidate_caption"))
        seq = SequenceMatcher(None, b, c).ratio()
        jac = _jaccard(b, c)
        drift = 1.0 - ((seq + jac) / 2.0)

        row = {
            "image_path": r["image_path"],
            "baseline_caption": b,
            "candidate_caption": c,
            "sequence_similarity": round(seq, 4),
            "token_jaccard": round(jac, 4),
            "caption_drift_score": round(drift, 4),
        }

        if "baseline_quality_score" in merged.columns:
            bq = float(r.get("baseline_quality_score") or 0.0)
            row["baseline_quality_score"] = round(bq, 4)
        if "candidate_quality_score" in merged.columns:
            cq = float(r.get("candidate_quality_score") or 0.0)
            row["candidate_quality_score"] = round(cq, 4)
        if "baseline_quality_score" in merged.columns and "candidate_quality_score" in merged.columns:
            row["quality_delta"] = round(float(row["candidate_quality_score"] - row["baseline_quality_score"]), 4)

        rows.append(row)

    drift_df = pd.DataFrame(rows).sort_values("caption_drift_score", ascending=False)
    drift_csv = out_dir / "caption_drift.csv"
    drift_df.to_csv(drift_csv, index=False)

    summary = {
        "pair_count": int(len(drift_df)),
        "caption_column": col,
        "baseline": str(baseline_path),
        "candidate": str(candidate_path),
        "mean_drift_score": round(float(drift_df["caption_drift_score"].mean()) if len(drift_df) else 0.0, 4),
        "median_drift_score": round(float(drift_df["caption_drift_score"].median()) if len(drift_df) else 0.0, 4),
        "high_drift_count": int((drift_df["caption_drift_score"] >= 0.5).sum()) if len(drift_df) else 0,
    }

    summary_path = out_dir / "caption_drift_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    md_lines = [
        "# Caption Drift Evaluation",
        "",
        f"Compared column: `{col}`",
        f"- Baseline: `{baseline_path}`",
        f"- Candidate: `{candidate_path}`",
        "",
        f"- Pair count: {summary['pair_count']}",
        f"- Mean drift score: {summary['mean_drift_score']}",
        f"- Median drift score: {summary['median_drift_score']}",
        f"- High drift count (>=0.5): {summary['high_drift_count']}",
        "",
        "## Top 10 Highest Drift",
        "",
    ]

    for _, r in drift_df.head(10).iterrows():
        md_lines.append(f"- `{r['image_path']}` | drift={r['caption_drift_score']} | sim={r['sequence_similarity']} | jac={r['token_jaccard']}")

    (out_dir / "caption_drift_report.md").write_text("\n".join(md_lines), encoding="utf-8")

    print(json.dumps({
        "status": "ok",
        "output_dir": str(out_dir),
        "pair_count": summary["pair_count"],
        "mean_drift_score": summary["mean_drift_score"],
    }, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
