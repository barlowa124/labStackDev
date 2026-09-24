# labStackDev — RNA-seq quantification pipelines for a stem cell lab

Reproducible, open-source RNA-seq processing that replaced a lab's
closed-source CLC Genomics Workbench workflow — and was validated against it
before adoption (**Pearson r = 0.984** on the lab's dataset).

**2-minute tour:** [Validation](#validation) for the concordance numbers,
[Pipelines](#pipelines) for what runs, [Design decisions](#design-decisions)
for the parts that required engineering judgment rather than defaults.

## Why this exists

The lab's expression results depended on a GUI-based commercial tool: results
were reproducible only by the person who clicked through it, runs were tied to
one workstation, and the workflow could not be version-controlled or tested.
These pipelines re-implement the quantification path in scriptable form
(Salmon, STAR+Salmon, pyDESeq2, METAFlux), keep the original outputs as a
regression baseline, and add the hardware-aware scheduling needed to run them
on the machines actually available.

## Validation

Quantification accuracy was validated against the lab's original CLC Genomics
Workbench baseline on the GSE267112 dataset on the author's hardware:

| Metric | Value |
|---|---|
| Pearson r vs CLC baseline | **0.984** |
| R² vs CLC baseline | **0.968** |
| Direct pseudoalignment | ~4 min/sample |
| STAR + Salmon hybrid | ~20 min/sample |

These figures are from the author's hardware and dataset; timings will vary
elsewhere. The comparison is per-sample on both TPM and counts, driven by
[`compare_ryan_salmon.py`](RNAseq_Pipelines/compare_ryan_salmon.py) with an
explicit `sample_map.txt` mapping — no fuzzy filename matching.

## Pipelines

All pipelines live in [`RNAseq_Pipelines/`](RNAseq_Pipelines/).

| Script | Purpose | Inputs | Outputs |
|---|---|---|---|
| `build_index_adaptive.sh` | Builds STAR and RSEM reference indexes; detects available RAM and uses a sparse STAR index (`--genomeSAsparseD 2`) when under 32 GB to avoid OOM | GRCh38 genome FASTA + GENCODE v45 GTF | STAR index, RSEM index |
| `run_salmon_pseudoalignment.sh` | Direct Salmon pseudoalignment; copies the Salmon index to a RAM disk, decompresses reads in memory with `pigz`, and runs one sequential job with 24 threads to avoid SSD I/O thrashing | Paired-end `*_1/2.fastq.gz`, Salmon index | `quant.sf` per sample in `Salmon_Quants_Ultra/` |
| `run_hybrid_salmon.sh` | Hybrid STAR+Salmon pipeline; STAR physically aligns reads and emits a transcriptome BAM, which is quantified by Salmon; genome is preloaded into RAM (`--genomeLoad LoadAndExit`) and 4 jobs run concurrently | Paired-end `*_1/2.fastq.gz`, STAR index, transcriptome FASTA | `quant.sf` per sample in `Salmon_Quants_Hybrid/` |
| `run_pydeseq2_pipeline.py` | Aggregates Salmon `quant.sf` files into a gene counts matrix (via tx2gene mapping) and runs pyDESeq2 differential expression | Sample metadata CSV, tx2gene CSV, Salmon quants | Counts matrix, DESeq2 normalized counts, pairwise contrast CSV |
| `run_metaflux_optimized.R` | Computes metabolic fluxes with METAFlux using a parallelized sparse-matrix OSQP solver (avoids the original 2.1 GB dense-matrix conversion) | TPM matrix CSV, METAFlux model data | `flux_results_salmon.csv` |
| `compare_ryan_salmon.py` | Validation: compares Salmon `quant.sf` outputs against CLC baseline quants using a `sample_map.txt` mapping; computes Pearson r and R² on TPM and counts | Baseline quants + `sample_map.txt`, pipeline quants | Per-sample correlation table CSV |

## Design decisions

- **RAM-disk staging over raw throughput.** The Salmon index is copied to a
  tmpfs mount before quantification and reads are decompressed in memory via
  `pigz`. On the lab's hardware the bottleneck was SSD I/O contention, not
  CPU — so the pseudoalignment pipeline runs *one* 24-thread job instead of
  parallel jobs, which is faster in wall-clock terms precisely because it
  avoids thrashing the disk.
- **Adaptive index building.** `build_index_adaptive.sh` checks available RAM
  and falls back to a sparse STAR index under 32 GB rather than failing with
  OOM mid-build — the common failure mode on the lab's smaller machines.
- **Preloaded genome for the hybrid path.** STAR's `--genomeLoad LoadAndExit`
  keeps the index resident so 4 concurrent jobs share one memory copy.
- **Sparse-matrix METAFlux.** The stock METAFlux path materializes a ~2.1 GB
  dense matrix; the R pipeline uses a parallelized sparse OSQP formulation
  instead, which is what makes the flux analysis fit on lab hardware at all.
- **Validation as a first-class script.** The CLC comparison is a runnable
  script with an explicit sample map, not a one-off notebook — the baseline
  regression can be re-run whenever a pipeline changes.

## Requirements

- [Salmon](https://combine-lab.github.io/salmon/) (`salmon quant`)
- [STAR](https://github.com/alexdobin/STAR)
- [RSEM](https://github.com/deweylab/RSEM) (`rsem-prepare-reference`)
- `pigz`, `zcat`, `xargs`, `find`, `nproc` (standard GNU coreutils)
- Python 3 with `pandas`, `numpy`, `scipy`, `pydeseq2`
- R with `METAFlux`, `data.table`, `doParallel`, `foreach`, `Matrix`, `osqp`, `stringi`, `stringr`
- Conda environments `rnaseq` and `salmon_env` (the scripts `conda activate` these)

## Usage

All paths are configured through environment variables (with repo-relative
defaults); a script exits with a clear message if a required input directory
does not exist:

| Variable | Default | Meaning |
|---|---|---|
| `LABSTACK_DATA_DIR` | `./data` | Input data: FASTQ directory (shell pipelines), reference FASTA/GTF directory (`build_index_adaptive.sh`), or TPM matrix directory (`run_metaflux_optimized.R`) |
| `LABSTACK_INDEX_DIR` | `./index` | Reference index root (`star_index/`, `salmon_index/`, transcriptome FASTA, generated STAR/RSEM indexes) |
| `LABSTACK_OUT_DIR` | `./results` | Output root for quantifications |
| `LABSTACK_THREADS` | all cores | Threads per STAR/Salmon job |
| `LABSTACK_METAFLUX_DIR` | `./METAFlux` | METAFlux source directory (R pipeline only) |

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

## Limitations

- Tuned for one lab's hardware (tmpfs/RAM-disk staging, high thread counts);
  on different storage topologies the parallelization choices may invert.
- Validated on a single dataset (GSE267112). The r = 0.984 concordance is
  evidence the pipeline reproduces the CLC baseline, not that either is
  biologically correct.
- RNA-seq quantification and DE for research use; not validated for clinical
  or diagnostic purposes.

## License

[Apache License 2.0](LICENSE)
