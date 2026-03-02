# METAFlux Pipeline Runbook

## Quick run

```bash
Rscript metaflux_pipeline_refactored.R <config.yaml>
```

Or on Windows:
```cmd
run_metaflux_refactored.bat [config.yaml]
```
(Defaults to `metaflux_config.example.yaml` if no arg.)

## Required inputs

| Item | Location | Description |
|------|----------|-------------|
| **project_root** | Config `paths.project_root` | Folder containing METAFlux assets |
| **rnaseq_file** | Config `paths.rnaseq_file` | RNA-seq Excel (genes × samples) |
| **human_gem.rda** | `project_root/` | Human GEM object |
| **cell_medium.rda** | `project_root/` | Cell medium profile |
| **nutrient_lookup_files.rda** | `project_root/` | Metabolite → reaction ID lookup |
| **data.R** | `project_root/` | Defines `calculate_reaction_score`, `compute_flux` |
| **calculate_score.R** | `project_root/` | (Can be empty if data.R provides functions) |
| **optimization.R** | `project_root/` | (Can be empty if data.R provides functions) |

## RNA-seq format

- Excel file with sheet index from config (`input.sheet_index`, default 1)
- Gene column name from config (`input.gene_column`, default `"Genes"`)
- Gene IDs: human gene symbols, unique, non-empty
- Expression: numeric, non-negative, no NA
- Minimum genes: `input.min_genes` (default 5000)

## Outputs

Written to `output.output_dir` or `project_root/runs/YYYYMMDD_HHMMSS/`:

- `flux_normal.csv`, `flux_knockout.csv`, `flux_combined.csv`
- `pathway_flux.csv`, `pathway_heatmap.png`
- `nutrient_flux_normal.csv`, `nutrient_flux_knockout.csv`, `nutrient_flux_boxplot.png`
- `run_metadata.json`

## Verified

- Pipeline runs end-to-end with METAFlux package data (Feb 2026)
- Test setup: `Rscript setup_metaflux_test.R` creates `METAFlux-Clean` with package data
