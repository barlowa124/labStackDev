from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd


def parse_image_metadata(image_path: str) -> Dict[str, Any]:
    p = Path(image_path)
    stem = p.stem.lower()

    plate_match = re.search(r"plate[_\- ]?(\d+|[a-z]\d+)", stem)
    well_match = re.search(r"\b([a-h][0-1]?\d)\b", stem)
    day_match = re.search(r"(?:day|d)[_\- ]?(\d{1,3})", stem)
    batch_match = re.search(r"(?:batch|b)[_\- ]?(\d{1,3})", stem)

    condition = None
    for key in ["sfm", "serum", "control", "treated", "vehicle", "dmem"]:
        if key in stem:
            condition = key
            break

    mode = None
    if any(k in stem for k in ["phase", "phasecontrast", "pc"]):
        mode = "phase-contrast"
    elif any(k in stem for k in ["fluor", "gfp", "rfp", "dapi"]):
        mode = "fluorescence"
    elif any(k in stem for k in ["bright", "bf"]):
        mode = "brightfield"

    return {
        "meta_filename": p.name,
        "meta_plate_id": plate_match.group(1) if plate_match else None,
        "meta_well_id": well_match.group(1).upper() if well_match else None,
        "meta_day": int(day_match.group(1)) if day_match else None,
        "meta_batch_id": batch_match.group(1) if batch_match else None,
        "meta_condition": condition,
        "meta_mode_hint": mode,
    }


def recapture_guidance(record: Dict[str, Any]) -> str:
    reasons: List[str] = []

    low_quality = bool(record.get("low_quality_flag", False))
    score = float(record.get("caption_quality_score") or 0.0)
    focus_var = float(record.get("features", {}).get("focus_variance") or 0.0)
    confluency = float(record.get("features", {}).get("confluency_fraction") or 0.0)
    edge_density = float(record.get("features", {}).get("edge_density") or 0.0)

    if low_quality and score < 0.45:
        reasons.append("Recapture recommended: caption quality below threshold")
    elif low_quality:
        reasons.append("Manual review recommended: borderline caption quality")

    if focus_var < 0.0015:
        reasons.append("Likely soft focus: refocus and recapture")
    if edge_density < 0.06:
        reasons.append("Low structural contrast: check illumination/exposure")
    if confluency < 0.03:
        reasons.append("Very low confluency: verify seeding density or field selection")

    if not reasons:
        return "No recapture action needed"
    return " | ".join(reasons)


def compute_condition_summary(df: pd.DataFrame) -> pd.DataFrame:
    if "meta_condition" not in df.columns:
        return pd.DataFrame()

    g = df.copy()
    g["meta_condition"] = g["meta_condition"].fillna("unknown")
    grouped = g.groupby("meta_condition", dropna=False)
    out = grouped.agg(
        image_count=("id", "count"),
        mean_confluency=("feat_confluency_fraction", "mean"),
        median_confluency=("feat_confluency_fraction", "median"),
        mean_caption_quality=("caption_quality_score", "mean"),
        low_quality_rate=("low_quality_flag", "mean"),
    ).reset_index()
    return out


def compute_batch_effects(df: pd.DataFrame) -> Dict[str, Any]:
    if "meta_batch_id" not in df.columns:
        return {"status": "no-batch-metadata"}

    g = df.copy()
    g["meta_batch_id"] = g["meta_batch_id"].fillna("unknown")

    batch_means = (
        g.groupby("meta_batch_id", dropna=False)["feat_confluency_fraction"]
        .mean()
        .dropna()
        .to_dict()
    )
    quality_means = (
        g.groupby("meta_batch_id", dropna=False)["caption_quality_score"]
        .mean()
        .dropna()
        .to_dict()
    )

    confluency_values = list(batch_means.values())
    spread = max(confluency_values) - min(confluency_values) if confluency_values else 0.0

    return {
        "status": "ok",
        "batch_count": len(batch_means),
        "confluency_mean_by_batch": batch_means,
        "quality_mean_by_batch": quality_means,
        "confluency_spread": round(float(spread), 4),
        "batch_effect_flag": bool(spread > 0.2),
    }


def sanity_check_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    warnings: List[Dict[str, Any]] = []

    required = {"meta_plate_id", "meta_well_id", "meta_day", "feat_confluency_fraction", "image_path"}
    if not required.issubset(df.columns):
        return warnings

    subset = df.dropna(subset=["meta_plate_id", "meta_well_id", "meta_day"]).copy()
    if subset.empty:
        return warnings

    subset = subset.sort_values(["meta_plate_id", "meta_well_id", "meta_day"])

    for (plate, well), group in subset.groupby(["meta_plate_id", "meta_well_id"]):
        prev = None
        for _, row in group.iterrows():
            if prev is not None:
                delta_day = int(row["meta_day"] - prev["meta_day"])
                delta_conf = float(row["feat_confluency_fraction"] - prev["feat_confluency_fraction"])
                if delta_day > 0 and abs(delta_conf) > 0.45:
                    warnings.append(
                        {
                            "type": "confluency-jump",
                            "plate": plate,
                            "well": well,
                            "from_day": int(prev["meta_day"]),
                            "to_day": int(row["meta_day"]),
                            "delta_confluency": round(delta_conf, 4),
                            "image_path": row["image_path"],
                        }
                    )
            prev = row

    return warnings


def compute_run_status(df: pd.DataFrame, failed_count: int) -> Dict[str, Any]:
    count = int(len(df))
    low_quality_rate = float(df["low_quality_flag"].mean()) if count and "low_quality_flag" in df.columns else 0.0
    median_quality = float(df["caption_quality_score"].median()) if count and "caption_quality_score" in df.columns else 0.0

    if failed_count > 0 or low_quality_rate > 0.30 or median_quality < 0.45:
        light = "Red"
    elif low_quality_rate > 0.15 or median_quality < 0.60:
        light = "Yellow"
    else:
        light = "Green"

    return {
        "run_status_light": light,
        "image_count": count,
        "failed_count": int(failed_count),
        "low_quality_rate": round(low_quality_rate, 4),
        "median_caption_quality": round(median_quality, 4),
    }


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def create_signed_manifest(
    out_root: Path,
    config_path: Path,
    model_id: str,
    device: str,
    record_count: int,
    failed_count: int,
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    files = [
        out_root / "records.csv",
        out_root / "records.jsonl",
        out_root / "run_metadata.json",
    ]

    file_hashes: Dict[str, str] = {}
    for file_path in files:
        if file_path.exists():
            file_hashes[file_path.name] = hash_file(file_path)

    payload = {
        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "config_path": str(config_path),
        "model_id": model_id,
        "device": device,
        "record_count": int(record_count),
        "failed_count": int(failed_count),
        "file_hashes": file_hashes,
    }
    if extra:
        payload["extra"] = extra

    manifest_text = json.dumps(payload, sort_keys=True)
    secret = os.environ.get("LAB_PIPELINE_MANIFEST_SECRET", "lab-default-secret")
    signature = hmac.new(secret.encode("utf-8"), manifest_text.encode("utf-8"), hashlib.sha256).hexdigest()

    signed = {
        "manifest": payload,
        "signature_sha256_hmac": signature,
        "signature_note": "Set LAB_PIPELINE_MANIFEST_SECRET in production for secure signing.",
    }
    return signed


def compute_sample_readiness(df: pd.DataFrame) -> pd.DataFrame:
    ready = df.copy()
    if ready.empty:
        return ready

    if "caption_quality_score" not in ready.columns:
        ready["caption_quality_score"] = 0.0
    if "low_quality_flag" not in ready.columns:
        ready["low_quality_flag"] = False
    if "feat_confluency_fraction" not in ready.columns:
        ready["feat_confluency_fraction"] = 0.0

    scores: List[float] = []
    status: List[str] = []
    for _, row in ready.iterrows():
        q = float(row.get("caption_quality_score") or 0.0)
        c = float(row.get("feat_confluency_fraction") or 0.0)
        low = bool(row.get("low_quality_flag", False))

        readiness = 0.65 * q + 0.35 * min(1.0, c * 1.5)
        if low:
            readiness -= 0.2
        readiness = max(0.0, min(1.0, readiness))
        scores.append(round(readiness, 4))

        if readiness >= 0.70:
            status.append("ready")
        elif readiness >= 0.50:
            status.append("review")
        else:
            status.append("hold")

    ready["sample_readiness_score"] = scores
    ready["sample_readiness_status"] = status
    return ready


def weekly_summary(run_dirs: Iterable[Path]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for run_dir in run_dirs:
        md = run_dir / "run_metadata.json"
        rec = run_dir / "records.csv"
        if not md.exists() or not rec.exists():
            continue
        try:
            meta = json.loads(md.read_text(encoding="utf-8"))
            df = pd.read_csv(rec)
        except Exception:
            continue

        rows.append(
            {
                "run_dir": str(run_dir),
                "processed_count": int(meta.get("processed_count", 0)),
                "failed_count": int(meta.get("failed_count", 0)),
                "median_caption_quality": float(df["caption_quality_score"].median()) if "caption_quality_score" in df.columns and len(df) else 0.0,
                "low_quality_rate": float(df["low_quality_flag"].mean()) if "low_quality_flag" in df.columns and len(df) else 0.0,
                "run_status_light": str(meta.get("run_status_light", "unknown")),
            }
        )

    if not rows:
        return {"status": "no-runs"}

    summary = {
        "status": "ok",
        "run_count": len(rows),
        "total_processed": int(sum(r["processed_count"] for r in rows)),
        "total_failed": int(sum(r["failed_count"] for r in rows)),
        "median_quality_across_runs": round(statistics.median(r["median_caption_quality"] for r in rows), 4),
        "mean_low_quality_rate": round(sum(r["low_quality_rate"] for r in rows) / len(rows), 4),
        "runs": rows,
    }
    return summary
