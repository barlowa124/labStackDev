from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException

from lab_ops import compute_sample_readiness

app = FastAPI(title="Lab Readiness API", version="1.0.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/readiness")
def readiness(records_csv: str) -> dict:
    path = Path(records_csv).expanduser()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"records file not found: {path}")

    df = pd.read_csv(path)
    ready = compute_sample_readiness(df)

    result = {
        "records_csv": str(path),
        "count": int(len(ready)),
        "ready_count": int((ready["sample_readiness_status"] == "ready").sum()) if len(ready) else 0,
        "review_count": int((ready["sample_readiness_status"] == "review").sum()) if len(ready) else 0,
        "hold_count": int((ready["sample_readiness_status"] == "hold").sum()) if len(ready) else 0,
        "mean_readiness_score": float(ready["sample_readiness_score"].mean()) if len(ready) else 0.0,
        "items": ready[[
            "image_path",
            "sample_readiness_score",
            "sample_readiness_status",
            "caption_quality_score",
            "low_quality_flag",
            "feat_confluency_fraction",
        ]].to_dict(orient="records"),
    }
    return result
