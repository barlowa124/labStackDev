# METAFlux Analyzer Integration Notes

## What this adds to the stack

- New analyzer module: `metaflux_analyzer.R`
- Runner entrypoint: `run_metaflux_analyzer.R`
- Config example: `metaflux_config.example.json`
- Metadata map example: `sample_metadata_map.example.csv`
- Pipeline position: post-normalization RNA expression -> MRAS -> flux inference -> plots/tables
- Outputs:
  - `nutrient_flux_boxplot.png`
  - `pathway_flux_heatmap.png`
  - `flux_results_normal.csv`
  - `flux_results_knockout.csv`
  - `pathway_flux_df.csv`
  - `metaflux_run_manifest.json`
  - `analyzer_telemetry_summary.json`
  - `telemetry_ai_report_metaflux.json`
  - `telemetry_team_report_metaflux.md`

## Why this improves over the original script

- Config-driven input paths and run options instead of hardcoded paths.
- Supports single-table sample metadata mapping to rename all normal and KO columns in one place.
- Stable function boundaries:
  - `read_sequence_data()`
  - `apply_gene_knockout()`
  - `build_nutrient_flux_df()`
  - `plot_nutrient_flux()`
  - `compute_pathway_flux_df()`
  - `plot_pathway_heatmap()`
  - `run_metaflux_analyzer()`
- Explicit validation for required files and packages.
- Safer knockout handling when a requested gene is absent.
- Reaction ID overrides are configurable (`reaction_override`) instead of hardcoded mutation logic.
- Reproducible exports (CSV + plots) for downstream traceability.
- Adds telemetry + data assessment bundle suitable for webapp governance workflows.
- Vectorized pathway scoring replaces nested loops for better runtime performance.

## Remaining script-level improvement opportunities

1. **Condition naming logic**
   - Current module sets only first column names (`normal_col_name`, `ko_col_name`) to preserve original behavior.
   - Better: map all sample columns through a condition metadata table.

2. **Nutrient lookup disambiguation**
   - Current selection uses first match via `grep`.
   - Better: exact metabolite dictionary with explicit reaction mapping by medium/model version.

3. **Pathway scoring robustness**
   - Current pathway activity uses mean absolute flux.
   - Better: include median and variance-normalized alternatives, then compare sensitivity.

4. **Error handling for `compute_flux`**
   - Add structured retry and solver diagnostics capture for `osqp` failures.

5. **Model/version pinning**
   - Capture METAFlux version and model asset hashes in each run report.

6. **Integration into Python webapp**
   - Add a thin Python launcher (`subprocess` Rscript wrapper) and expose outputs in `lab_webui.py`.

## Suggested next integration step

- Add a small config file (JSON/YAML) consumed by an `Rscript` entrypoint:
  - `run_metaflux_analyzer.R`
  - this enables one-click invocation from the existing webapp stack.
