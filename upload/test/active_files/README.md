# Cell Image -> Text Pipeline (Python)

This pipeline converts microscopy/cell images into AI-friendly text records by combining:
1. Quantitative morphology features
2. Optional Hugging Face image captioning
3. Structured outputs (JSONL/CSV/Markdown)

## Files
- `run_pipeline.py` - CLI entrypoint
- `pipeline.py` - pipeline orchestration
- `features.py` - morphology/quality feature extraction
- `caption.py` - optional HF caption model wrapper
- `io_utils.py` - image listing and PPTX extraction
- `lab_ops.py` - metadata parsing, readiness scoring, run status, governance helpers
- `evaluate_caption_drift.py` - compares caption drift across two runs/models
- `evaluate_model_promotion.py` - policy check for promoting a candidate model
- `generate_weekly_pi_summary.py` - weekly summary for PI/lab manager
- `export_eln_lims_package.py` - creates ELN/LIMS-ready package + zip
- `lab_api.py` - local API with sample readiness endpoint
- `Run_Lab_WebUI.bat` - one-click web dashboard launcher (router + Streamlit, IE fallback for legacy browsers)
- `lab_webui.py` - Streamlit UI for non-technical lab workflows
- `lab_webui_router.py` - IE/legacy browser fallback (port 8502)
- `launch_lab_webui_with_ie_fallback.py` - starts router + Streamlit, opens browser
- `config.example.yaml` - config template
- `metaflux_pipeline_refactored.R` - METAFlux R pipeline (pathway heatmap, nutrient boxplot)
- `metaflux_config.example.yaml` - METAFlux config

## METAFlux (R)
Requires R with packages: `METAFlux`, `readxl`, `ggplot2`, `pheatmap`, `RColorBrewer`, `jsonlite`, `yaml`, `stringi`, `stringr`, `osqp`. Run from the METAFlux tab in the lab dashboard.

## Install
Supported Python versions: **3.10 to 3.14**.

```bash
python -m venv .venv
.venv\\Scripts\\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Quick compatibility check:

```bash
python check_python_compat.py
```

## Run
```bash
python run_pipeline.py --config C:/Users/asdf/Documents/cell_image_text_pipeline/config.example.yaml
```

## Default behavior
- Extracts image objects from your PPTX
- Computes per-image metrics:
  - confluency estimate
  - cell count estimate
  - morphology proxies (eccentricity/solidity)
  - contact density proxy
  - focus variance and edge density
- Generates optional model captions (BLIP)
- Creates combined text records suitable for downstream LLM/RAG usage
- Automatically emits microscopy-safe rewritten caption fields while preserving original model captions
- Adds caption quality scoring (keywords, length, entropy) and low-quality review flags
- Applies deterministic caption post-rules by mode (`phase-contrast`, `fluorescence`, `brightfield`)
- Supports resume/retry checkpointing for interrupted long runs
- Supports hardware policy auto-selection for model/device/batch size

## Output artifacts
Under `output.root_dir`:
- `records/record_XXXX.json` (per image)
- `records.jsonl`
- `records.csv`
- `low_quality_records.csv` (flagged rows, if enabled)
- `report.md`
- `run_metadata.json`
- `checkpoint.json` (if resume enabled)
- `failed_records.json` (if failures occur)
- `run_status.json` + `run_status.md` (traffic-light decision)
- `condition_summary.csv` (condition-level stats)
- `batch_effects.json` (batch effect indicators)
- `sanity_warnings.json` (time-series/logic warnings)
- `run_manifest_signed.json` (signed provenance manifest)
- `artifacts/pptx_extracted_images/*`

Each record includes:
- `model_caption` and `model_caption_original` (original model output)
- `model_caption_microscopy_safe` (sanitized microscopy-safe text)
- `text_record_microscopy_safe` (feature summary + sanitized caption)
- `caption_quality_score`, `caption_entropy`, `caption_length_tokens`
- `low_quality_flag`, `low_quality_reason`
- `recapture_guidance`
- metadata fields parsed from filename (`meta_plate_id`, `meta_well_id`, `meta_day`, `meta_batch_id`, `meta_condition`)
- `sample_readiness_score`, `sample_readiness_status`

## Config highlights
- `captioning.mode`: `phase-contrast` | `fluorescence` | `brightfield`
- `hardware_policy.device_policy`: `auto` | `cpu` | `gpu`
- `hardware_policy.{cpu_model_id,gpu_model_id}` for auto model selection
- `runtime.resume_enabled`, `runtime.retry_attempts`, `runtime.retry_backoff_seconds`
- `quality.low_quality_threshold`, `quality.domain_keywords`, `quality.banned_terms`

## One-click launchers (non-technical users)
- Daily QC: `Run_Daily_QC.bat`
- Weekly model drift benchmark: `Run_Weekly_Drift_Check.bat`
- Export ELN/LIMS package: `Export_ELN_Package.bat`
- Web dashboard: `Run_Lab_WebUI.bat`
- Auto instrument ingest: `Run_Auto_Instrument_Bridge.bat`

## Automatic instrument ingest bridge
Use `instrument_bridge.py` to monitor one or more instrument output folders and auto-trigger pipeline runs when new images appear.

This works with:
- Local microscope/instrument export directories
- Network share paths
- Google Drive Desktop synced folders (configure the local synced path)

Optional direct Google Drive pull is also supported via `google_workspace` config (OAuth token + folder ID).

Configure `instrument_bridge` in your YAML:

```yaml
instrument_bridge:
  enabled: true
  poll_seconds: 30
  recursive: true
  min_new_images: 1
  state_file: "C:/Users/asdf/Documents/cell_image_text_pipeline/.instrument_bridge_state.json"
  staging_root: "C:/Users/asdf/Documents/cell_image_text_pipeline/instrument_ingest"
  sources:
    - "C:/LabInstrumentExports/MicroscopeA"
    - "C:/Users/asdf/Google Drive/Shared drives/Lab Imaging/Instrument Drop"
```

Run once for a dry check:

```bash
python instrument_bridge.py --config C:/Users/asdf/Documents/cell_image_text_pipeline/config.validation_ops.yaml --once
```

Run continuously:

```bash
python instrument_bridge.py --config C:/Users/asdf/Documents/cell_image_text_pipeline/config.validation_ops.yaml
```

### Google Workspace doctor
Check whether your local OAuth token includes required scopes for Drive/Calendar/Gmail automation:

```bash
python google_workspace_doctor.py --token C:/Users/asdf/Documents/token.json --credentials C:/Users/asdf/Documents/credentials.json
```

If coverage is incomplete, run OAuth again with these scopes:
- `https://www.googleapis.com/auth/drive.readonly`
- `https://www.googleapis.com/auth/calendar.events`
- `https://www.googleapis.com/auth/gmail.send`

## Lab Web UI (recommended for non-CS users)
Run:

```bash
Run_Lab_WebUI.bat
```

The dashboard opens in your browser and provides tabs for:
- Daily QC pipeline run
- Drift evaluation + model promotion decision
- Weekly PI summary generation
- ELN/LIMS package export
- Sample readiness triage preview
- METAFlux (RNA-seq metabolic flux: pathway heatmap, nutrient boxplot, config/upload)
- Cell/Media visualizations (3D + density heatmaps)
- Collaboration (when lab_collab installed)

Default startup is **Streamlined (recommended)** mode:
- Step 1: Run Daily QC
- Step 2: Compute Readiness
- Step 3: Export ELN/LIMS package

This guided path is optimized for first-time/non-technical users under time pressure.

## License and data sharing

- Code license: `Apache-2.0` (see `LICENSE`)

Important: this repository is open for code, but data is not automatically open.
Only commit data that is explicitly approved for public release.

The dashboard also includes:
- **In-Lab Custom** mode (full controls)
- **Lab Language mode** toggle (plain in-lab wording instead of technical terms)
- **Glutamate reminder** banner in both modes
- **Bug Reporter** that saves AI-crawlable `.md` + `.json` reports to `bug_reports/`
- **Pre-export QC checklist gate** (glutamate checks + data-save + anomaly notes)
- **Failure replay** action to retry failed items from prior runs
- **Run fingerprint** generator (`run_fingerprint.json`) for audit/reproducibility
- **Alerts & Trends** panel (7/30-day trends + readiness/quality/failure alerts)

Analyzer telemetry is now emitted for each run in the output folder:
- `analyzer_telemetry.jsonl`
- `analyzer_telemetry_summary.json`

You can export consolidated telemetry in two formats:
- Team shareable report (`.md`)
- AI-crawlable report (`.json`)

Example:

```bash
python export_telemetry_reports.py \
  --runs-root C:/Users/asdf/Documents/cell_image_text_pipeline \
  --team-output C:/Users/asdf/Documents/cell_image_text_pipeline/telemetry_team_report.md \
  --ai-output C:/Users/asdf/Documents/cell_image_text_pipeline/telemetry_ai_report.json \
  --pattern "output_*" \
  --window-days 30
```

## Caption drift evaluation
Compare two runs (same benchmark images, potentially different models):

```bash
python evaluate_caption_drift.py \
  --baseline C:/path/to/baseline/records.csv \
  --candidate C:/path/to/candidate/records.csv \
  --output C:/path/to/drift_eval
```

Outputs:
- `caption_drift.csv`
- `caption_drift_summary.json`
- `caption_drift_report.md`

## One-command benchmark suite
Run base subset model + large subset model + drift evaluation in one command:

```bash
python run_benchmark_suite.py
```

Optional overrides:

```bash
python run_benchmark_suite.py \
  --python C:/Users/asdf/Documents/cell_image_text_pipeline/.venv311/Scripts/python.exe \
  --project-root C:/Users/asdf/Documents/cell_image_text_pipeline
```

## Weekly PI summary
```bash
python generate_weekly_pi_summary.py \
  --runs-root C:/Users/asdf/Documents/cell_image_text_pipeline \
  --pattern "output_*" \
  --output C:/Users/asdf/Documents/cell_image_text_pipeline/weekly_pi_summary.md
```

## Model promotion policy
```bash
python evaluate_model_promotion.py \
  --baseline C:/Users/asdf/Documents/cell_image_text_pipeline/output_caption_subset/records.csv \
  --candidate C:/Users/asdf/Documents/cell_image_text_pipeline/output_caption_subset_bliplarge/records.csv \
  --output C:/Users/asdf/Documents/cell_image_text_pipeline/model_promotion_decision.json
```

## ELN/LIMS package export
```bash
python export_eln_lims_package.py \
  --run-dir C:/Users/asdf/Documents/cell_image_text_pipeline/output_caption_microscopy_full_bliplarge \
  --out-dir C:/Users/asdf/Documents/cell_image_text_pipeline/eln_packages
```

## Local readiness API endpoint
Install dependencies and run:

```bash
uvicorn lab_api:app --host 127.0.0.1 --port 8008
```

Query endpoint:

```bash
http://127.0.0.1:8008/readiness?records_csv=C:/Users/asdf/Documents/cell_image_text_pipeline/output_caption_subset/records.csv
```

## Notes
- If the HF model fails to load, the pipeline still runs with feature-based text summaries.
- For production microscopy quality, consider replacing segmentation with Cellpose/StarDist while keeping the same output schema.
