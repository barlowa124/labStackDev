# Consolidation Plan: cell_image_text_pipeline → labStackDev

**Goal:** labStackDev is the main repo. Merge useful parts from cell_image_text_pipeline and deprecate the rest.

---

## Current State

| Repo | Contents |
|------|----------|
| **labStackDev** | lab_webui (3D, Collaboration, METAFlux), METAFlux R scripts, RNA-seek reference. No pipeline, no run scripts. |
| **cell_image_text_pipeline** | Full pipeline (run_pipeline, features, caption, lab_ops), IE fallback, launcher, configs. No 3D view. |

---

## Merge Strategy

### Phase 1: Add pipeline infrastructure to labStackDev

**Target:** `upload/test/active_files/` (lab app root)

**Copy from cell_image_text_pipeline:**
- `lab_ops.py`, `python_compat.py`, `check_python_compat.py`
- `caption.py`, `features.py`, `io_utils.py`, `telemetry.py`
- `pipeline.py`, `run_pipeline.py`
- `export_eln_lims_package.py`, `generate_weekly_pi_summary.py`, `run_benchmark_suite.py`, `export_telemetry_reports.py`
- `evaluate_caption_drift.py`, `evaluate_model_promotion.py`
- `instrument_bridge.py`, `lab_api.py`
- `lab_webui_router.py`, `launch_lab_webui_with_ie_fallback.py`
- `config.example.yaml` (or `config.validation_ops.yaml` if available)
- `requirements.txt`
- `Run_Lab_WebUI.bat`

### Phase 2: Merge lab_webui

**Base:** labStackDev `lab_webui.py` (keeps 3D, Collaboration, power-user features)

**Add from cell_image_text_pipeline:**
- METAFlux tab: YAML config, RNA-seq upload, report bundle (ZIP)
- IE fallback integration (router already handles; ensure lab_webui paths work)

**Fix:**
- Make `lab_collab` optional (try/except) so app runs without it
- Add `plotly` to requirements if missing

### Phase 3: Add run scripts and config

- `Run_Lab_WebUI.bat` → `pip install -r requirements.txt`, run launcher
- `config.example.yaml` for pipeline

### Phase 4: Deprecate cell_image_text_pipeline

- Add `README_DEPRECATED.md` in cell_image_text_pipeline pointing to labStackDev
- Or remove cell_image_text_pipeline folder after verification

---

## Files to NOT copy (cell_image_text_pipeline)

- `add_speaker_notes_*.py`, `create_lab_effectiveness_presentation.py` – one-off scripts
- `analyze_presentation_equipment_by_id.py`, `find_lab_equipment_*.py` – presentation tools
- `check_google_workspace.py`, `google_workspace_doctor.py`, `reauth_*.py`, `verify_*.py` – Google auth utilities
- `demo_jabeen_multimodal_placeholder.py` – demo
- `dump_presentation_data_by_id.py`, `list_*_presentations*.py` – presentation listing
- `launch_lab_webui.py` – superseded by `launch_lab_webui_with_ie_fallback.py`
- `run_caption_validation.py` – validation helper (optional)

---

## Dependency Check

Pipeline imports: `caption`, `features`, `io_utils`, `lab_ops`, `telemetry`. All must be present in active_files.

---

## Verification

1. `cd labStackDev/upload/test/active_files`
2. `pip install -r requirements.txt`
3. `python launch_lab_webui_with_ie_fallback.py` – should start router + Streamlit
4. Open http://127.0.0.1:8502 – IE fallback or redirect
5. Verify tabs: Daily QC, Drift, Weekly, ELN, Readiness, Alerts, Cell/Media Viz (3D), METAFlux, Collaboration (if lab_collab), Bug
