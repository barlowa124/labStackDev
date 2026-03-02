# Lab Stack Consolidation Plan

**Date:** 2026-02-13  
**Goal:** Consolidate `cell_image_text_pipeline` into `labStackDev` as the single source of truth.

---

## What Was Merged (cell_image_text_pipeline → labStackDev)

### Pipeline modules (copied to `upload/test/active_files/`)
- `caption.py`, `features.py`, `io_utils.py`, `lab_ops.py`, `python_compat.py`
- `pipeline.py`, `telemetry.py`, `run_pipeline.py`
- `export_eln_lims_package.py`, `generate_weekly_pi_summary.py`, `run_benchmark_suite.py`, `export_telemetry_reports.py`
- `evaluate_caption_drift.py`, `evaluate_model_promotion.py`
- `instrument_bridge.py`, `lab_api.py`

### IE fallback & launcher
- `lab_webui_router.py` – Flask router (port 8502) for legacy browsers
- `launch_lab_webui_with_ie_fallback.py` – Starts router + Streamlit, opens browser
- `Run_Lab_WebUI.bat` – One-click launcher (pip install, then launch)

### Config & dependencies
- `config.example.yaml` – Pipeline config template
- `requirements.txt` – Updated with `plotly>=5.0.0` for 3D visualizer

### lab_webui.py changes
- **lab_collab optional** – App runs without `lab_collab`; Collaboration tab shows info message
- **METAFlux tab** – New tab with YAML config, RNA-seq upload, report bundle download
- **run_metaflux_refactored()** – Runs `metaflux_pipeline_refactored.R` with YAML
- **render_metaflux_results()** – Heatmap, boxplot, CSVs, ZIP bundle

---

## labStackDev Features (kept)

- 3D Cell Visualizer (Plotly, Blender-style portholes)
- Collaboration tab (when `lab_collab` installed)
- Power-user tooltips, operator walkthrough
- METAFlux Analyzer (JSON) in streamlined/custom views
- All existing tabs: Daily QC, Drift, Weekly, ELN, Readiness, Alerts, Cell/Media Viz, Bug

---

## How to Run

1. **From `upload/test/active_files/`:**
   ```bat
   Run_Lab_WebUI.bat
   ```
   Or:
   ```bat
   pip install -r requirements.txt
   python launch_lab_webui_with_ie_fallback.py
   ```

2. **Create a venv** (optional, in same folder):
   ```bat
   py -3 -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   Run_Lab_WebUI.bat
   ```

3. **Browser:** Opens `http://127.0.0.1:8502` – router redirects modern browsers to Streamlit (8503), serves IE fallback for legacy.

---

## What to Deprecate (cell_image_text_pipeline)

After verifying labStackDev works:

- **cell_image_text_pipeline** can be archived or used only as a reference
- Keep `Documents/metaflux_pipeline_refactored.R` and `metaflux_config.example.yaml` if they are the canonical copies; otherwise use `active_files/` versions

---

## Dependencies

- **lab_collab** – Optional. If missing, Collaboration tab shows info message.
- **R + METAFlux** – Required for METAFlux tab. Rscript must be on PATH or specified.
