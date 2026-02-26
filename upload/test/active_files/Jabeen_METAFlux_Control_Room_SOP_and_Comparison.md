# Jabeen METAFlux Workflow: Control-Room SOP + Current-State Comparison

## Purpose
Standardize Jabeen's two-part METAFlux process into a control-room operating model:
1) nutrient flux boxplot analysis, then  
2) pathway heatmap analysis,  
with automation for routine execution and human review for scientific decisions.

## 1-Page SOP (Control-Room Model)

## Scope
- Input: RNA-seq matrix, sample metadata map, knockout gene set, medium profile, run config.
- Output: nutrient boxplot, pathway heatmap, flux tables, run manifest, telemetry summary.
- Human role: approve run, review exceptions, interpret biological meaning, approve downstream actions.

## Workflow (Execution Path)
1. **Intake + Validation Gate**
   - Check matrix schema (`Genes` column, numeric sample columns, non-empty samples).
   - Validate metadata map (all sample columns mapped).
   - Validate knockout genes exist in dataset.
   - Validate medium profile + required METAFlux model assets.
   - Gate result: `pass | warn | fail`.

2. **Run Setup (Control Room)**
   - Analyst selects config (normal vs KO labels, nutrient panel, pathway selection policy).
   - System records assumptions snapshot (model version, medium version, overrides).
   - Analyst approves start.

3. **Automated Compute Block**
   - Compute MRAS for normal and knockout conditions.
   - Run flux optimization for both sets.
   - Build nutrient flux data and plot boxplot.
   - Build pathway flux matrix and plot heatmap.

4. **Post-Run Quality Gate**
   - Check solver diagnostics and runtime completion.
   - Check output completeness (all expected files present).
   - Run sanity checks (missingness, obvious out-of-range behavior, reaction mapping conflicts).
   - Gate result: `ready | review | hold`.

5. **Human Review and Decision**
   - Analyst reviews boxplot/heatmap + exception flags.
   - Decide: `accept`, `rerun with changes`, or `escalate for PI review`.
   - Record rationale in run notes.

6. **Export + Governance**
   - Export ELN/LIMS package and run status summary.
   - Persist run manifest, telemetry, config snapshot, assumptions hash.
   - Publish PI-facing weekly summary metrics.

## Minimum Required Artifacts per Run
- `nutrient_flux_boxplot.png`
- `pathway_flux_heatmap.png`
- `flux_results_normal.csv`
- `flux_results_knockout.csv`
- `pathway_flux_df.csv`
- `metaflux_run_manifest.json`
- `analyzer_telemetry_summary.json`
- `telemetry_team_report_metaflux.md`

---

## Existing Workflow vs Control-Room SOP

| Area | Existing Jabeen Script Workflow | Control-Room SOP Workflow | Practical Benefit |
|---|---|---|---|
| Run initiation | Manual script edits and `setwd()` path changes | Config-driven run with approved start in control room | Fewer setup errors, faster kickoff |
| Input validation | Limited preflight checks | Structured pass/warn/fail validation gate | Fewer failed runs due to bad inputs |
| Knockout handling | Can fail silently if gene absent | Explicit knockout existence check and fail/warn policy | Safer biological interpretation |
| Nutrient mapping | `grep`-style first match and hardcoded citrate fix | Controlled reaction mapping policy with logged overrides | Better reproducibility and less ambiguity |
| Plot generation | Manual parameter edits in script | Parameterized plots from config template | Consistent outputs across runs/users |
| Pathway scoring | Manual loop workflow | Standardized scoring policy and exported matrix | Comparable results across experiments |
| Error handling | Rerun manually after failures | Post-run gate + exception review path | Less wasted analyst time |
| Governance | Limited run provenance | Manifest, telemetry, assumptions snapshot, audit trail | Committee-safe traceability |
| Human role | Human does both routine mechanics and scientific review | Automation handles routine mechanics; human handles scientific decisions | Better morale and focus on high-value work |
| Throughput pattern | Operator-limited | Pipeline-limited with exception-only human intervention | More runs per week at stable quality |

---

## What Changes Immediately (First 2 Weeks)
- Use the integrated `run_metaflux_analyzer.R` entrypoint only (no ad hoc script edits).
- Require metadata mapping file for all sample columns.
- Enforce pass/warn/fail gate before compute.
- Enforce ready/review/hold gate after compute.
- Save and review the same artifact bundle every run.

## KPI Set for Comparison (Before vs After)
- Time to run completion (minutes/run)
- Rerun rate due to input/setup errors
- Fraction of runs with complete artifact bundle
- Analyst hands-on time per run
- Time from run completion to PI-ready summary
- Rate of unresolved exceptions at handoff

## Decision Rule
If the control-room SOP reduces analyst hands-on time and rerun rate without reducing result quality, migrate routine runs to automated execution and keep humans in exception review + scientific interpretation mode.
