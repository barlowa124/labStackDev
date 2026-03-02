from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import yaml
from PIL import Image

from caption import Captioner
from features import FeatureConfig, extract_density_products, extract_features, summarize_features_text
from io_utils import ensure_dirs, extract_images_from_pptx, list_images
from lab_ops import (
    compute_batch_effects,
    compute_condition_summary,
    compute_run_status,
    compute_sample_readiness,
    create_signed_manifest,
    parse_image_metadata,
    recapture_guidance,
    sanity_check_records,
)
from telemetry import AnalyzerTelemetry


@dataclass
class PipelineOutput:
    output_root: Path
    processed_count: int
    records: List[Dict]


def _compose_text_record(feature_text: str, model_caption: str | None, include_model: bool, include_features: bool) -> str:
    parts: List[str] = []
    if include_features and feature_text:
        parts.append(feature_text)
    if include_model and model_caption:
        parts.append(f"Vision-language description: {model_caption}")
    return "\n".join(parts).strip()


def _detect_device(policy: str) -> str:
    policy_norm = (policy or "auto").strip().lower()
    cuda_available = False
    try:
        import torch

        cuda_available = bool(torch.cuda.is_available())
    except Exception:
        cuda_available = False

    if policy_norm == "gpu":
        return "cuda" if cuda_available else "cpu"
    if policy_norm == "cpu":
        return "cpu"
    return "cuda" if cuda_available else "cpu"


def _resolve_caption_runtime(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cap_cfg = cfg.get("captioning", {})
    hw_cfg = cfg.get("hardware_policy", {})

    device = _detect_device(hw_cfg.get("device_policy", "auto"))

    model_id_cfg = (cap_cfg.get("model_id") or "").strip()
    if not model_id_cfg or model_id_cfg.lower() == "auto":
        if device == "cuda":
            model_id = hw_cfg.get("gpu_model_id", "Salesforce/blip-image-captioning-large")
        else:
            model_id = hw_cfg.get("cpu_model_id", "Salesforce/blip-image-captioning-base")
    else:
        model_id = model_id_cfg

    batch_size_cfg = cap_cfg.get("batch_size")
    if batch_size_cfg is None:
        batch_size = int(hw_cfg.get("batch_size_gpu", 4) if device == "cuda" else hw_cfg.get("batch_size_cpu", 1))
    else:
        batch_size = int(batch_size_cfg)

    return {
        "device": device,
        "model_id": model_id,
        "batch_size": max(1, batch_size),
    }


def _sanitize_caption_microscopy(text: str | None) -> str | None:
    if text is None:
        return None

    out = text.strip()
    if not out:
        return out

    replacements = [
        (r"\ba close up of\b", "a microscopy field showing"),
        (r"\bbunch of\b", "cluster of"),
        (r"\bfish\b", "cell-like structures"),
        (r"\bfrosty surface\b", "granular cellular texture"),
        (r"\bfrost\b", "granular texture"),
        (r"\bwater droplets\b", "bright speckled artifacts"),
        (r"\bpond\b", "culture medium background"),
        (r"\bblack and white photo\b", "grayscale microscopy image"),
        (r"\bphone\b", "specimen timeline"),
    ]

    for pattern, replacement in replacements:
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)

    out = re.sub(r"\s+", " ", out).strip()
    return out


def _apply_mode_post_rules(text: str | None, mode: str) -> str | None:
    if not text:
        return text

    mode_norm = (mode or "").strip().lower()
    out = text.strip()

    if mode_norm == "fluorescence":
        out = re.sub(r"\bbright speckled artifacts\b", "fluorescent puncta", out, flags=re.IGNORECASE)
        out = re.sub(r"\bgrayscale microscopy image\b", "fluorescence microscopy image", out, flags=re.IGNORECASE)
        if "fluorescence" not in out.lower():
            out = f"fluorescence microscopy image showing {out}"
    elif mode_norm == "phase-contrast":
        out = re.sub(r"\bgrayscale microscopy image\b", "phase-contrast microscopy image", out, flags=re.IGNORECASE)
        if "phase-contrast" not in out.lower():
            out = f"phase-contrast microscopy field showing {out}"
    elif mode_norm == "brightfield":
        out = re.sub(r"\bgrayscale microscopy image\b", "brightfield microscopy image", out, flags=re.IGNORECASE)
        if "brightfield" not in out.lower():
            out = f"brightfield microscopy image showing {out}"

    out = re.sub(r"\s+", " ", out).strip()
    return out


def _word_entropy(text: str) -> float:
    tokens = re.findall(r"[a-zA-Z]+", text.lower())
    if not tokens:
        return 0.0

    counts: Dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1

    total = len(tokens)
    ent = 0.0
    for count in counts.values():
        p = count / total
        ent -= p * math.log2(p)
    return ent


def _caption_quality(
    caption: str | None,
    domain_keywords: List[str],
    banned_terms: List[str],
    low_quality_threshold: float,
) -> Dict[str, Any]:
    if not caption:
        return {
            "caption_quality_score": 0.0,
            "caption_length_tokens": 0,
            "caption_entropy": 0.0,
            "caption_keyword_hit_fraction": 0.0,
            "caption_banned_term_hits": 0,
            "low_quality_flag": True,
            "low_quality_reason": "empty-caption",
        }

    text = caption.strip()
    lower = text.lower()
    tokens = re.findall(r"[a-zA-Z]+", lower)
    token_count = len(tokens)

    if token_count < 6:
        length_score = token_count / 6.0
    elif token_count <= 35:
        length_score = 1.0
    elif token_count <= 60:
        length_score = max(0.4, 1.0 - ((token_count - 35) / 50.0))
    else:
        length_score = 0.2

    keyword_hits = 0
    keyword_count = max(1, len(domain_keywords))
    for kw in domain_keywords:
        if kw.lower() in lower:
            keyword_hits += 1
    keyword_fraction = keyword_hits / keyword_count

    banned_hits = 0
    for term in banned_terms:
        if re.search(rf"\b{re.escape(term.lower())}\b", lower):
            banned_hits += 1
    banned_penalty = min(0.4, banned_hits * 0.15)

    entropy_raw = _word_entropy(text)
    entropy_score = min(1.0, entropy_raw / 3.5)

    microscopy_anchor = 1.0 if ("microscopy" in lower or "cell" in lower) else 0.0

    score = (
        0.45 * keyword_fraction
        + 0.25 * length_score
        + 0.20 * entropy_score
        + 0.10 * microscopy_anchor
        - banned_penalty
    )
    score = max(0.0, min(1.0, score))

    low_quality = score < low_quality_threshold
    reason_parts = []
    if keyword_fraction < 0.2:
        reason_parts.append("low-domain-keywords")
    if banned_hits > 0:
        reason_parts.append("contains-banned-terms")
    if token_count < 6:
        reason_parts.append("too-short")
    if not reason_parts and low_quality:
        reason_parts.append("score-below-threshold")

    return {
        "caption_quality_score": round(score, 4),
        "caption_length_tokens": token_count,
        "caption_entropy": round(entropy_raw, 4),
        "caption_keyword_hit_fraction": round(keyword_fraction, 4),
        "caption_banned_term_hits": banned_hits,
        "low_quality_flag": bool(low_quality),
        "low_quality_reason": ",".join(reason_parts) if reason_parts else "",
    }


def _compose_safe_text_record(feature_text: str, safe_caption: str | None, include_model: bool, include_features: bool) -> str:
    parts: List[str] = []
    if include_features and feature_text:
        parts.append(feature_text)
    if include_model and safe_caption:
        parts.append(f"Vision-language description (microscopy-safe): {safe_caption}")
    return "\n".join(parts).strip()


def _load_spectral_calibration_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    s_cfg = cfg.get("spectral_calibration", {}) if isinstance(cfg, dict) else {}
    return {
        "enabled": bool(s_cfg.get("enabled", False)),
        "white_balance_mode": str(s_cfg.get("white_balance_mode", "grayworld")).strip().lower(),
        "gamma_correction": float(s_cfg.get("gamma_correction", 1.0)),
        "color_correction_matrix": s_cfg.get("color_correction_matrix", []),
        "reference_patch_rgb": s_cfg.get("reference_patch_rgb", [0.5, 0.5, 0.5]),
        "save_preview": bool(s_cfg.get("save_preview", True)),
    }


def _load_density_analysis_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    d_cfg = cfg.get("density_analysis", {}) if isinstance(cfg, dict) else {}
    return {
        "enabled": bool(d_cfg.get("enabled", True)),
        "grid_size": int(d_cfg.get("grid_size", 24)),
        "save_artifacts": bool(d_cfg.get("save_artifacts", True)),
    }


def _apply_color_correction_matrix(img: np.ndarray, matrix_values: List[float]) -> np.ndarray:
    if not isinstance(matrix_values, list) or len(matrix_values) != 9:
        return img
    try:
        mat = np.array(matrix_values, dtype=np.float32).reshape(3, 3)
    except Exception:
        return img
    h, w, _ = img.shape
    reshaped = img.reshape(-1, 3)
    corrected = np.clip(reshaped @ mat.T, 0.0, 1.0)
    return corrected.reshape(h, w, 3)


def _apply_spectral_calibration(image_path: Path, cal_cfg: Dict[str, Any], preview_dir: Path) -> tuple[Path, Dict[str, Any]]:
    img = Image.open(image_path).convert("RGB")
    arr = np.asarray(img).astype(np.float32) / 255.0
    before_mean = arr.mean(axis=(0, 1)).tolist()

    wb_mode = str(cal_cfg.get("white_balance_mode", "grayworld")).lower()
    if wb_mode == "grayworld":
        ch_mean = arr.mean(axis=(0, 1)) + 1e-8
        gray_target = float(ch_mean.mean())
        gains = gray_target / ch_mean
        arr = np.clip(arr * gains.reshape(1, 1, 3), 0.0, 1.0)
    elif wb_mode == "reference_patch":
        target = cal_cfg.get("reference_patch_rgb", [0.5, 0.5, 0.5])
        if isinstance(target, list) and len(target) == 3:
            ch_mean = arr.mean(axis=(0, 1)) + 1e-8
            target_arr = np.array(target, dtype=np.float32)
            gains = np.clip(target_arr / ch_mean, 0.2, 5.0)
            arr = np.clip(arr * gains.reshape(1, 1, 3), 0.0, 1.0)

    arr = _apply_color_correction_matrix(arr, cal_cfg.get("color_correction_matrix", []))

    gamma = float(cal_cfg.get("gamma_correction", 1.0))
    if gamma > 0 and abs(gamma - 1.0) > 1e-6:
        arr = np.clip(arr, 0.0, 1.0) ** (1.0 / gamma)

    after_mean = arr.mean(axis=(0, 1)).tolist()
    delta = [float(after_mean[i] - before_mean[i]) for i in range(3)]

    out_path = image_path
    if bool(cal_cfg.get("save_preview", True)):
        preview_dir.mkdir(parents=True, exist_ok=True)
        out_path = preview_dir / image_path.name
        Image.fromarray((np.clip(arr, 0.0, 1.0) * 255.0).astype(np.uint8)).save(out_path)

    return out_path, {
        "calibration_applied": True,
        "white_balance_mode": wb_mode,
        "gamma_correction": gamma,
        "channel_mean_before": [round(float(v), 6) for v in before_mean],
        "channel_mean_after": [round(float(v), 6) for v in after_mean],
        "channel_mean_delta": [round(float(v), 6) for v in delta],
    }


def _spectral_consistency(feats: Dict[str, Any], calibration_meta: Dict[str, Any] | None = None) -> Dict[str, Any]:
    r = float(feats.get("channel_mean_r", 0.0))
    g = float(feats.get("channel_mean_g", 0.0))
    b = float(feats.get("channel_mean_b", 0.0))
    s = max(1e-8, r + g + b)
    rn, gn, bn = r / s, g / s, b / s
    balance_std = float(np.std([rn, gn, bn]))

    sat = float(feats.get("mean_saturation", 0.0))
    focus = float(feats.get("focus_variance", 0.0))
    focus_score = min(1.0, focus / 0.02)
    sat_score = 1.0 - min(1.0, abs(sat - 0.35) / 0.35)
    balance_score = 1.0 - min(1.0, balance_std / 0.2)

    score = 0.50 * balance_score + 0.25 * sat_score + 0.25 * focus_score

    if calibration_meta and isinstance(calibration_meta, dict):
        delta = calibration_meta.get("channel_mean_delta", [0.0, 0.0, 0.0])
        if isinstance(delta, list) and len(delta) == 3:
            drift_mag = float(np.linalg.norm(np.array(delta, dtype=np.float32)))
            if drift_mag > 0.35:
                score -= 0.15

    score = max(0.0, min(1.0, score))
    drift_flag = bool(score < 0.45)
    reason = "spectral-score-below-threshold" if drift_flag else ""
    return {
        "spectral_consistency_score": round(float(score), 4),
        "spectral_drift_flag": drift_flag,
        "spectral_warning_reason": reason,
    }


def _load_checkpoint(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"completed": {}, "failed": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"completed": {}, "failed": {}}


def _save_checkpoint(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_pipeline(config_path: Path) -> PipelineOutput:
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    out_root = Path(cfg["output"]["root_dir"]).expanduser()
    records_dir, artifacts_dir = ensure_dirs(out_root)
    telemetry = AnalyzerTelemetry(output_root=out_root, component="pipeline-analyzer")
    telemetry.log("pipeline_started", config_path=str(config_path), output_root=str(out_root))
    calibration_cfg = _load_spectral_calibration_config(cfg)
    density_cfg = _load_density_analysis_config(cfg)
    calibration_preview_dir = artifacts_dir / "calibrated_preview"
    density_map_dir = artifacts_dir / "density_maps"
    telemetry.log("calibration_config_loaded", enabled=calibration_cfg.get("enabled", False), white_balance_mode=calibration_cfg.get("white_balance_mode"))
    telemetry.log("density_config_loaded", enabled=density_cfg.get("enabled", False), grid_size=density_cfg.get("grid_size"))

    image_dir = (cfg["input"].get("image_dir") or "").strip()
    pptx_path = (cfg["input"].get("pptx_path") or "").strip()

    images: List[Path] = []
    if image_dir:
        image_root = Path(image_dir).expanduser()
        images.extend(list_images(image_root, cfg["input"].get("recursive", True), cfg["input"].get("image_extensions", [])))

    if pptx_path:
        slide_extract_dir = artifacts_dir / "pptx_extracted_images"
        images.extend(extract_images_from_pptx(Path(pptx_path).expanduser(), slide_extract_dir))

    # de-duplicate while preserving order
    seen = set()
    dedup_images = []
    for img in images:
        key = str(img.resolve()) if img.exists() else str(img)
        if key not in seen and img.exists():
            dedup_images.append(img)
            seen.add(key)
    images = dedup_images
    telemetry.log("images_discovered", image_count=len(images), has_pptx=bool(pptx_path), has_image_dir=bool(image_dir))

    feature_cfg = FeatureConfig(
        min_object_size_px=int(cfg["features"].get("min_object_size_px", 30)),
        contact_distance_px=int(cfg["features"].get("contact_distance_px", 45)),
    )

    runtime_cfg = cfg.get("runtime", {})
    resume_enabled = bool(runtime_cfg.get("resume_enabled", True))
    retry_attempts = max(1, int(runtime_cfg.get("retry_attempts", 2)))
    retry_backoff_seconds = float(runtime_cfg.get("retry_backoff_seconds", 1.5))
    checkpoint_file = runtime_cfg.get("checkpoint_file")
    checkpoint_path = Path(checkpoint_file).expanduser() if checkpoint_file else (out_root / "checkpoint.json")

    quality_cfg = cfg.get("quality", {})
    domain_keywords = quality_cfg.get(
        "domain_keywords",
        [
            "cell",
            "cells",
            "confluency",
            "morphology",
            "microscopy",
            "density",
            "cluster",
            "phase",
            "fluorescence",
            "brightfield",
        ],
    )
    banned_terms = quality_cfg.get("banned_terms", ["fish", "pond", "frost", "water", "droplets"])
    low_quality_threshold = float(quality_cfg.get("low_quality_threshold", 0.45))
    save_low_quality_csv = bool(quality_cfg.get("save_low_quality_csv", True))

    cap_runtime = _resolve_caption_runtime(cfg)
    mode = (cfg.get("captioning", {}).get("mode") or "phase-contrast").strip().lower()

    captioner = Captioner(
        enabled=bool(cfg["captioning"].get("enabled", True)),
        model_id=cap_runtime["model_id"],
        max_new_tokens=int(cfg["captioning"].get("max_new_tokens", 40)),
        task_prompt=cfg["captioning"].get("task_prompt", "<MORE_DETAILED_CAPTION>"),
        device=cap_runtime["device"],
        batch_size=cap_runtime["batch_size"],
    )
    prompt = cfg["captioning"].get("prompt")

    records: List[Dict] = []
    failed_records: List[Dict[str, Any]] = []
    checkpoint = _load_checkpoint(checkpoint_path) if resume_enabled else {"completed": {}, "failed": {}}
    completed_map: Dict[str, Any] = checkpoint.get("completed", {}) if isinstance(checkpoint, dict) else {}
    resumed_count = 0

    for idx, image_path in enumerate(images, start=1):
        image_key = str(image_path)
        if resume_enabled and image_key in completed_map:
            resumed = completed_map[image_key]
            resumed["id"] = idx
            records.append(resumed)
            resumed_count += 1
            continue

        last_error: str | None = None
        record: Dict[str, Any] | None = None
        calibration_meta: Dict[str, Any] | None = None
        analysis_image_path = image_path
        if calibration_cfg.get("enabled", False):
            try:
                analysis_image_path, calibration_meta = _apply_spectral_calibration(image_path, calibration_cfg, calibration_preview_dir)
                telemetry.log("calibration_applied", image_path=image_key, calibrated_image_path=str(analysis_image_path))
            except Exception as cal_exc:
                calibration_meta = {
                    "calibration_applied": False,
                    "calibration_error": str(cal_exc),
                }
                telemetry.log("calibration_failed", image_path=image_key, error=str(cal_exc))
                analysis_image_path = image_path
        for attempt in range(1, retry_attempts + 1):
            try:
                feats = extract_features(analysis_image_path, feature_cfg)
                density_data = None
                if density_cfg.get("enabled", False):
                    density_data = extract_density_products(
                        analysis_image_path,
                        grid_size=int(density_cfg.get("grid_size", 24)),
                        max_dim_px=int(feature_cfg.max_dim_px),
                    )
                feature_text = summarize_features_text(feats)
                model_caption = captioner.generate(analysis_image_path, prompt=prompt)
                safe_caption = _apply_mode_post_rules(_sanitize_caption_microscopy(model_caption), mode=mode)

                text_record = _compose_text_record(
                    feature_text=feature_text,
                    model_caption=model_caption,
                    include_model=bool(cfg["text"].get("include_model_caption", True)),
                    include_features=bool(cfg["text"].get("include_feature_summary", True)),
                )
                safe_text_record = _compose_safe_text_record(
                    feature_text=feature_text,
                    safe_caption=safe_caption,
                    include_model=bool(cfg["text"].get("include_model_caption", True)),
                    include_features=bool(cfg["text"].get("include_feature_summary", True)),
                )

                qc = _caption_quality(
                    caption=safe_caption,
                    domain_keywords=domain_keywords,
                    banned_terms=banned_terms,
                    low_quality_threshold=low_quality_threshold,
                )

                record = {
                    "id": idx,
                    "image_path": image_key,
                    "analysis_image_path": str(analysis_image_path),
                    "features": feats,
                    "feature_summary": feature_text,
                    "caption_mode": mode,
                    "model_caption": model_caption,
                    "model_caption_original": model_caption,
                    "model_caption_microscopy_safe": safe_caption,
                    "text_record": text_record,
                    "text_record_microscopy_safe": safe_text_record,
                    **qc,
                    **_spectral_consistency(feats, calibration_meta=calibration_meta),
                }
                record.update(parse_image_metadata(image_key))
                if calibration_meta:
                    record["spectral_calibration"] = calibration_meta
                if density_data:
                    record["density_analysis"] = {
                        "grid_size": density_data.get("grid_size"),
                        "density_mean": round(float(density_data.get("density_mean", 0.0)), 6),
                        "density_max": round(float(density_data.get("density_max", 0.0)), 6),
                        "density_std": round(float(density_data.get("density_std", 0.0)), 6),
                        "media_fraction": round(float(density_data.get("media_fraction", 0.0)), 6),
                        "media_intensity_mean": round(float(density_data.get("media_intensity_mean", 0.0)), 6),
                        "media_texture_variance": round(float(density_data.get("media_texture_variance", 0.0)), 6),
                    }
                    if density_cfg.get("save_artifacts", True):
                        density_map_dir.mkdir(parents=True, exist_ok=True)
                        heatmap_df = pd.DataFrame(density_data["density_heatmap"])
                        heatmap_df.to_csv(density_map_dir / f"record_{idx:04d}_heatmap.csv", index=False)
                        wavetable_df = pd.DataFrame(
                            {
                                "x_index": list(range(len(density_data["wavetable_x"]))),
                                "wavetable_x_density": density_data["wavetable_x"],
                                "wavetable_y_density": density_data["wavetable_y"],
                            }
                        )
                        wavetable_df.to_csv(density_map_dir / f"record_{idx:04d}_wavetable.csv", index=False)
                    telemetry.log(
                        "density_products_computed",
                        image_path=image_key,
                        density_mean=round(float(density_data.get("density_mean", 0.0)), 6),
                        media_fraction=round(float(density_data.get("media_fraction", 0.0)), 6),
                    )
                telemetry.log(
                    "spectral_proxy_computed",
                    image_path=image_key,
                    spectral_consistency_score=record.get("spectral_consistency_score"),
                    spectral_drift_flag=record.get("spectral_drift_flag"),
                )
                if bool(record.get("spectral_drift_flag", False)):
                    telemetry.log(
                        "spectral_quality_gate_triggered",
                        image_path=image_key,
                        reason=record.get("spectral_warning_reason", ""),
                    )
                record["recapture_guidance"] = recapture_guidance(record)
                break
            except Exception as exc:
                last_error = str(exc)
                if attempt < retry_attempts:
                    time.sleep(retry_backoff_seconds * attempt)

        if record is None:
            fail = {
                "id": idx,
                "image_path": image_key,
                "error": last_error or "unknown-error",
                "retry_attempts": retry_attempts,
            }
            failed_records.append(fail)
            telemetry.log("record_failed", image_path=image_key, error=fail["error"], retry_attempts=retry_attempts)
            if resume_enabled:
                checkpoint.setdefault("failed", {})[image_key] = fail
                _save_checkpoint(checkpoint_path, checkpoint)
            continue

        records.append(record)
        if idx == 1 or idx % 25 == 0:
            telemetry.log("record_processed_progress", processed_count=len(records), failed_count=len(failed_records), last_image=image_key)

        if bool(cfg["output"].get("save_per_image_json", True)):
            per_image = records_dir / f"record_{idx:04d}.json"
            per_image.write_text(json.dumps(record, indent=2), encoding="utf-8")

        if resume_enabled:
            checkpoint.setdefault("completed", {})[image_key] = record
            checkpoint.setdefault("failed", {}).pop(image_key, None)
            _save_checkpoint(checkpoint_path, checkpoint)

    if bool(cfg["output"].get("save_jsonl", True)):
        jsonl_path = out_root / "records.jsonl"
        with jsonl_path.open("w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    run_status = {
        "run_status_light": "Yellow",
        "image_count": len(records),
        "failed_count": len(failed_records),
        "low_quality_rate": 0.0,
        "median_caption_quality": 0.0,
    }

    if bool(cfg["output"].get("save_csv", True)):
        rows = []
        for r in records:
            row = {
                "id": r["id"],
                "image_path": r["image_path"],
                "analysis_image_path": r.get("analysis_image_path"),
                "meta_filename": r.get("meta_filename"),
                "meta_plate_id": r.get("meta_plate_id"),
                "meta_well_id": r.get("meta_well_id"),
                "meta_day": r.get("meta_day"),
                "meta_batch_id": r.get("meta_batch_id"),
                "meta_condition": r.get("meta_condition"),
                "meta_mode_hint": r.get("meta_mode_hint"),
                "feature_summary": r["feature_summary"],
                "caption_mode": r.get("caption_mode"),
                "model_caption": r["model_caption"],
                "model_caption_original": r.get("model_caption_original"),
                "model_caption_microscopy_safe": r.get("model_caption_microscopy_safe"),
                "text_record": r["text_record"],
                "text_record_microscopy_safe": r.get("text_record_microscopy_safe"),
                "recapture_guidance": r.get("recapture_guidance"),
                "caption_quality_score": r.get("caption_quality_score"),
                "caption_length_tokens": r.get("caption_length_tokens"),
                "caption_entropy": r.get("caption_entropy"),
                "caption_keyword_hit_fraction": r.get("caption_keyword_hit_fraction"),
                "caption_banned_term_hits": r.get("caption_banned_term_hits"),
                "low_quality_flag": r.get("low_quality_flag"),
                "low_quality_reason": r.get("low_quality_reason"),
                "spectral_consistency_score": r.get("spectral_consistency_score"),
                "spectral_drift_flag": r.get("spectral_drift_flag"),
                "spectral_warning_reason": r.get("spectral_warning_reason"),
                "density_mean": ((r.get("density_analysis") or {}).get("density_mean") if isinstance(r.get("density_analysis"), dict) else None),
                "density_max": ((r.get("density_analysis") or {}).get("density_max") if isinstance(r.get("density_analysis"), dict) else None),
                "density_std": ((r.get("density_analysis") or {}).get("density_std") if isinstance(r.get("density_analysis"), dict) else None),
                "media_fraction": ((r.get("density_analysis") or {}).get("media_fraction") if isinstance(r.get("density_analysis"), dict) else None),
                "media_intensity_mean": ((r.get("density_analysis") or {}).get("media_intensity_mean") if isinstance(r.get("density_analysis"), dict) else None),
                "media_texture_variance": ((r.get("density_analysis") or {}).get("media_texture_variance") if isinstance(r.get("density_analysis"), dict) else None),
            }
            row.update({f"feat_{k}": v for k, v in r["features"].items() if k != "image_path"})
            rows.append(row)

        df = pd.DataFrame(rows)
        if not df.empty:
            df = compute_sample_readiness(df)
        df.to_csv(out_root / "records.csv", index=False)

        if save_low_quality_csv and not df.empty and "low_quality_flag" in df.columns:
            df[df["low_quality_flag"] == True].to_csv(out_root / "low_quality_records.csv", index=False)

        if not df.empty:
            condition_df = compute_condition_summary(df)
            if not condition_df.empty:
                condition_df.to_csv(out_root / "condition_summary.csv", index=False)

            batch_effects = compute_batch_effects(df)
            (out_root / "batch_effects.json").write_text(json.dumps(batch_effects, indent=2), encoding="utf-8")

            sanity_warnings = sanity_check_records(df)
            (out_root / "sanity_warnings.json").write_text(json.dumps(sanity_warnings, indent=2), encoding="utf-8")

            run_status = compute_run_status(df, failed_count=len(failed_records))
            if "spectral_drift_flag" in df.columns:
                run_status["spectral_drift_count"] = int((df["spectral_drift_flag"] == True).sum())
                run_status["spectral_drift_rate"] = round(float((df["spectral_drift_flag"] == True).mean()), 4)
        else:
            run_status = {
                "run_status_light": "Red",
                "image_count": 0,
                "failed_count": len(failed_records),
                "low_quality_rate": 0.0,
                "median_caption_quality": 0.0,
                "spectral_drift_count": 0,
                "spectral_drift_rate": 0.0,
            }

    (out_root / "run_status.json").write_text(json.dumps(run_status, indent=2), encoding="utf-8")
    (out_root / "run_status.md").write_text(
        "\n".join(
            [
                "# Run Traffic-Light Status",
                "",
                f"- Status: {run_status['run_status_light']}",
                f"- Image count: {run_status['image_count']}",
                f"- Failed count: {run_status['failed_count']}",
                f"- Low quality rate: {run_status['low_quality_rate']}",
                f"- Median caption quality: {run_status['median_caption_quality']}",
            ]
        ),
        encoding="utf-8",
    )

    if failed_records:
        (out_root / "failed_records.json").write_text(json.dumps(failed_records, indent=2), encoding="utf-8")

    if bool(cfg["output"].get("save_markdown_report", True)):
        md_lines = ["# Cell Image Text Conversion Report", ""]
        md_lines.append(f"Processed images: {len(records)}")
        md_lines.append("")
        if captioner.error:
            md_lines.append(f"Captioning warning: {captioner.error}")
            md_lines.append("")
        for r in records[:80]:
            md_lines.append(f"## Record {r['id']}")
            md_lines.append(f"- Image: {r['image_path']}")
            md_lines.append(f"- Feature summary: {r['feature_summary']}")
            md_lines.append(f"- Model caption: {r['model_caption']}")
            md_lines.append(f"- Model caption (microscopy-safe): {r.get('model_caption_microscopy_safe')}")
            md_lines.append(f"- Caption quality score: {r.get('caption_quality_score')}")
            md_lines.append(f"- Low quality flag: {r.get('low_quality_flag')} ({r.get('low_quality_reason')})")
            md_lines.append(f"- Text record: {r['text_record']}")
            md_lines.append(f"- Text record (microscopy-safe): {r.get('text_record_microscopy_safe')}")
            md_lines.append("")
        (out_root / "report.md").write_text("\n".join(md_lines), encoding="utf-8")

    run_meta = {
        "processed_count": len(records),
        "failed_count": len(failed_records),
        "resumed_count": resumed_count,
        "output_root": str(out_root),
        "captioning_enabled": captioner.enabled,
        "captioning_error": captioner.error,
        "caption_mode": mode,
        "selected_model_id": cap_runtime["model_id"],
        "selected_device": cap_runtime["device"],
        "selected_batch_size": cap_runtime["batch_size"],
        "run_status_light": run_status.get("run_status_light"),
        "spectral_calibration_enabled": bool(calibration_cfg.get("enabled", False)),
        "spectral_calibration_mode": calibration_cfg.get("white_balance_mode"),
        "resume_enabled": resume_enabled,
        "checkpoint_path": str(checkpoint_path),
        "config_path": str(config_path),
    }

    telemetry.log(
        "pipeline_completed",
        processed_count=len(records),
        failed_count=len(failed_records),
        resumed_count=resumed_count,
        run_status_light=run_status.get("run_status_light"),
    )
    telemetry_events_path, telemetry_summary_path = telemetry.write_files()
    run_meta["analyzer_telemetry_events"] = str(telemetry_events_path)
    run_meta["analyzer_telemetry_summary"] = str(telemetry_summary_path)
    (out_root / "run_metadata.json").write_text(json.dumps(run_meta, indent=2), encoding="utf-8")

    signed_manifest = create_signed_manifest(
        out_root=out_root,
        config_path=config_path,
        model_id=cap_runtime["model_id"],
        device=cap_runtime["device"],
        record_count=len(records),
        failed_count=len(failed_records),
        extra={"run_status_light": run_status.get("run_status_light")},
    )
    (out_root / "run_manifest_signed.json").write_text(json.dumps(signed_manifest, indent=2), encoding="utf-8")

    return PipelineOutput(output_root=out_root, processed_count=len(records), records=records)
