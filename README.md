> **This repository has moved.** Active development continues in [barlowa124/lab-informatics](https://github.com/barlowa124/lab-informatics) under [`labStackDev/`](https://github.com/barlowa124/lab-informatics/tree/main/labStackDev). This repo is archived and kept for link stability.

---

# labStackDev - RNA-seq quantification pipelines for a stem cell lab

These RNA-seq pipelines replaced a lab's CLC Genomics Workbench workflow. They were compared with the original outputs before adoption, with Pearson r = 0.984 on the lab's dataset.

[Validation](#validation) records the comparison. [Pipelines](#pipelines) lists the scripts. [Design decisions](#design-decisions) explains the implementation choices.

## Why this exists

The lab's original workflow relied on GUI actions tied to one workstation. These pipelines make those steps scriptable and version-controlled. They use Salmon and a STAR/Salmon hybrid for quantification, followed by pyDESeq2 or METAFlux analysis. The original outputs provide a regression baseline. Scheduling is tuned to the lab's hardware.

## Validation

Quantification outputs were compared with the lab's CLC Genomics Workbench baseline on GSE267112, using the author's hardware.

| Metric | Value |
|---|---|
| Pearson r vs CLC baseline | **0.984** |
| R² vs CLC baseline | **0.968** |
| Direct pseudoalignment | ~4 min/sample |
| STAR + Salmon hybrid | ~20 min/sample |

These figures are from the author's hardware and dataset. Timings will vary
elsewhere. The comparison is per-sample on both TPM and counts, driven by
[`compare_ryan_salmon.py`](RNAseq_Pipelines/compare_ryan_salmon.py) with an
explicit `sample_map.txt` mapping, no fuzzy filename matching.

## Pipelines

All pipelines live in [`RNAseq_Pipelines/`](RNAseq_Pipelines/).

| Script | Purpose | Inputs | Outputs |
|---|---|---|---|
| `build_index_adaptive.sh` | Builds STAR, RSEM, and Salmon reference indexes; detects available RAM and uses a sparse STAR index (`--genomeSAsparseD 2`) when under 32 GB to avoid OOM | GRCh38 genome FASTA + GENCODE v45 GTF + `gencode.v45.transcripts.fa` | STAR index (`star_index/`), RSEM index, Salmon index (`salmon_index/`) |
| `run_salmon_pseudoalignment.sh` | Direct Salmon pseudoalignment; copies the Salmon index to a RAM disk, decompresses reads in memory with `pigz`, and runs one sequential job with 24 threads to avoid SSD I/O thrashing | Paired-end `*_1/2.fastq.gz`, Salmon index | `quant.sf` per sample in `Salmon_Quants_Ultra/` |
| `run_hybrid_salmon.sh` | Hybrid STAR+Salmon pipeline; STAR physically aligns reads and emits a transcriptome BAM, which is quantified by Salmon; genome is preloaded into RAM (`--genomeLoad LoadAndExit`) and 4 jobs run concurrently | Paired-end `*_1/2.fastq.gz`, STAR index, transcriptome FASTA | `quant.sf` per sample in `Salmon_Quants_Hybrid/` |
| `run_pydeseq2_pipeline.py` | Aggregates Salmon `quant.sf` files into a gene counts matrix (via tx2gene mapping) and runs pyDESeq2 differential expression | Sample metadata CSV, tx2gene CSV, Salmon quants | Counts matrix, DESeq2 normalized counts, pairwise contrast CSV |
| `run_metaflux_optimized.R` | Computes metabolic fluxes with METAFlux using a parallelized sparse-matrix OSQP solver (avoids the original 2.1 GB dense-matrix conversion) | TPM matrix CSV, METAFlux model data | `flux_results_salmon.csv` |
| `compare_ryan_salmon.py` | Validation: compares Salmon `quant.sf` outputs against CLC baseline quants using a `sample_map.txt` mapping; computes Pearson r and R² on TPM and counts | Baseline quants + `sample_map.txt`, pipeline quants | Per-sample correlation table CSV |

## Design decisions

- **RAM-disk staging over raw throughput.** The Salmon index is copied to a
  tmpfs mount before quantification and reads are decompressed in memory via
  `pigz`. On the lab's hardware the bottleneck was SSD I/O contention, not
  CPU, so the pseudoalignment pipeline runs *one* 24-thread job instead of
  parallel jobs, which is faster in wall-clock terms because it
  avoids thrashing the disk.
- **Adaptive index building.** `build_index_adaptive.sh` checks available RAM
  and falls back to a sparse STAR index under 32 GB instead of failing with
  OOM mid-build, the common failure mode on the lab's smaller machines.
- **Preloaded genome for the hybrid path.** STAR's `--genomeLoad LoadAndExit`
  keeps the index resident so 4 concurrent jobs share one memory copy.
- **Sparse-matrix METAFlux.** The stock METAFlux path materializes a ~2.1 GB
  dense matrix. The R pipeline uses a parallelized sparse OSQP formulation
  instead, which is what makes the flux analysis fit on lab hardware at all.
- **Validation as a runnable script.** The CLC comparison is a runnable
  script with an explicit sample map, not a one-off notebook. The baseline
  regression can be re-run whenever a pipeline changes.

## Requirements

### Command-line tools

- [Salmon](https://combine-lab.github.io/salmon/) (`salmon quant`)
- [STAR](https://github.com/alexdobin/STAR)
- [RSEM](https://github.com/deweylab/RSEM) (`rsem-prepare-reference`)
- `pigz`, `zcat`, `xargs`, `find`, `nproc` (standard GNU coreutils)

### Language environments

- Python 3 with `pandas`, `numpy`, `scipy`, `pydeseq2`
- R with `METAFlux`, `data.table`, `doParallel`, `foreach`, `Matrix`, `osqp`, `stringi`, `stringr`
- Conda environments `rnaseq` and `salmon_env` (the scripts `conda activate` these)

## Usage

All paths are configured through environment variables (with repo-relative
defaults). A script exits with a clear message if a required input directory
does not exist:

| Variable | Default | Meaning |
|---|---|---|
| `LABSTACK_DATA_DIR` | `./data` | Input data: FASTQ directory (shell pipelines), reference FASTA/GTF directory (`build_index_adaptive.sh`), or TPM matrix directory (`run_metaflux_optimized.R`) |
| `LABSTACK_INDEX_DIR` | `./index` | Reference index root (`star_index/`, `salmon_index/`, transcriptome FASTA, generated STAR/RSEM indexes) |
| `LABSTACK_OUT_DIR` | `./results` | Output root for quantifications |
| `LABSTACK_THREADS` | all cores | Threads per STAR/Salmon job |
| `LABSTACK_METAFLUX_DIR` | `./METAFlux` | METAFlux source directory (R pipeline only) |
| `LABSTACK_METADATA` | `./GEO_Submission_Metadata.csv` | Sample metadata CSV (pyDESeq2 pipeline only) |
| `LABSTACK_TX2GENE` | `./salmon_tx2gene.csv` | Transcript-to-gene map (pyDESeq2 pipeline only) |
| `LABSTACK_QUANTS_DIR` | `./results/Salmon_Quants_Ultra` | Per-SRR `quant.sf` directory (pyDESeq2 and comparison scripts) |

```bash
# Build reference indexes (adapts to available RAM)
LABSTACK_DATA_DIR=/path/to/reference bash RNAseq_Pipelines/build_index_adaptive.sh

# Direct pseudoalignment (~4 min/sample)
LABSTACK_DATA_DIR=/path/to/fastq bash RNAseq_Pipelines/run_salmon_pseudoalignment.sh

# Hybrid STAR + Salmon alignment (~20 min/sample)
LABSTACK_DATA_DIR=/path/to/fastq bash RNAseq_Pipelines/run_hybrid_salmon.sh

# Differential expression
python RNAseq_Pipelines/run_pydeseq2_pipeline.py

# Metabolic flux analysis
Rscript RNAseq_Pipelines/run_metaflux_optimized.R

# Validate against CLC baseline
python RNAseq_Pipelines/compare_ryan_salmon.py
```

## LIMS layer

[`lims/registry.py`](lims/registry.py) is a minimal lab-information layer
(SQLite, stdlib-only) for the records side the pipelines do not cover:
sample registration, experiment status transitions, plate-well assignment,
and result tracking by content hash. The differentiating piece is the
audit log: every mutation appends a row whose SHA-256 covers the row
content plus the previous audit hash. Structural verification detects edited
rows and broken interior links. Detecting tail or whole-log truncation requires
a separately retained `audit_checkpoint()`, supplied to `verify_audit_chain()`
as `expected_head` and `expected_rows`. Keep that checkpoint independently of
the database.
Experiment status is a forward-only state machine
(`registered → queued → assigned → processed → analyzed → locked`);
locked experiments refuse further mutation.

Each mutation appends an audit row linked to the previous row by a SHA-256 hash. Tests cover edited rows and a missing interior row. The chain alone cannot detect removal of its final rows or an attacker rewriting the entire chain. That requires a separately trusted copy of the final hash: callers retain an `audit_checkpoint()` snapshot and pass it back as `expected_head`/`expected_rows` to `verify_audit_chain()`.

[`lims/demo_lims.py`](lims/demo_lims.py) runs a synthetic 16-sample batch. Its saved outputs are [`results/lims_summary.json`](results/lims_summary.json) and [`results/lims_audit_log.csv`](results/lims_audit_log.csv).

This prototype has no user interface or ELN narrative editor. It does not connect to instruments.

## Limitations

- Tuned for one lab's hardware (tmpfs/RAM-disk staging, high thread counts).
  On different storage topologies the parallelization choices may invert.
- Validated on a single dataset (GSE267112). The r = 0.984 concordance is
  evidence the pipeline reproduces the CLC baseline, not that either is
  biologically correct. The per-sample correlation table is not committed:
  it compares against the lab's CLC exports, which are not public data.
- RNA-seq quantification and DE for research use. Not validated for clinical
  or diagnostic purposes.


## Related work

- [cultivated-meat-multiomic](https://github.com/barlowa124/cultivated-meat-multiomic) builds its metabolic-flux panel on the METAFlux quantification path in this repo.

## Scientific data migration

Run `python -m lims.migrate --samples examples/migration/samples.csv --assays examples/migration/assays.csv --db migration.sqlite3 --output migration-output/preview --dry-run` to review a synthetic import. Remove `--dry-run` and choose a new output directory to apply it.

The sample CSV requires `sample_id,kind`. The assay CSV requires `assay_id,sample_id,assay,value,unit`.

IDs are trimmed and uppercased. All rows sharing a normalized ID are rejected. An assay must reference a sample accepted in the same import. Values must be finite. Supported units are `g/L`, `mg/L`, `mmol/L`, `AU` and `%`. Units are not converted. Unterminated quoted fields stop the import.

The report retains every parsed record with its outcome and rejection reasons. SQLite stores the original source bytes and their hashes. Accepted records and audit entries are written in one transaction.

`committed` describes the current call. Dry runs and replays return false. A replay also sets `previously_committed` to true and writes no new records. Replays are identified by source bytes and mapping version. Output directories must be new, and the database cannot share a path with an output artifact.

### Acceptance walkthrough

| Requirement | Evidence |
|---|---|
| Do not merge ambiguous identifiers | Both `S-2` sample rows are rejected by `test_migration.py` |
| Do not lose rejected records | Reconciliation retains every raw record and its rejection reasons |
| Preserve source identity | Tests compare stored source bytes and SHA-256 hashes |
| Avoid duplicate imports | Replay tests check unchanged table counts |
| Recover from a write failure | An injected exception rolls back domain records and audit entries |

This is a CSV migration exercise. It does not demonstrate an enterprise LIMS deployment or regulated validation.

## License

[Apache License 2.0](LICENSE)
