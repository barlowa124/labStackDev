# labStackDev — RNA-seq quantification pipelines for a stem cell lab

This repository collects the optimized RNA-seq processing pipelines developed for a stem cell
lab's transcriptomics work. It includes a Salmon pseudoalignment pipeline and a STAR+Salmon
hybrid pipeline with RAM-disk/pigz/threading optimizations, an adaptive STAR index builder,
a pyDESeq2 differential expression pipeline, a METAFlux metabolic flux pipeline, and a
validation script that compares pipeline output against a CLC Genomics Workbench baseline.

All pipelines live in [`RNAseq_Pipelines/`](RNAseq_Pipelines/).

## Validation

Quantification accuracy was validated against the lab's original CLC Genomics Workbench
baseline on the GSE267112 dataset on the author's hardware:

- **Pearson r = 0.984** and **R² = 0.968** vs the CLC baseline.
- **~4 minutes per sample** for the direct pseudoalignment pipeline.
- **~20 minutes per sample** for the STAR + Salmon hybrid pipeline.

These figures are from the author's hardware and dataset; timings will vary elsewhere.

## Pipelines

| Script | Purpose | Inputs | Outputs |
|---|---|---|---|
| `build_index_adaptive.sh` | Builds STAR and RSEM reference indexes; detects available RAM and uses a sparse STAR index (`--genomeSAsparseD 2`) when under 32 GB to avoid OOM | GRCh38 genome FASTA + GENCODE v45 GTF | STAR index, RSEM index |
| `run_salmon_pseudoalignment.sh` | Direct Salmon pseudoalignment; copies the Salmon index to a RAM disk, decompresses reads in memory with `pigz`, and runs one sequential job with 24 threads to avoid SSD I/O thrashing | Paired-end `*_1/2.fastq.gz`, Salmon index | `quant.sf` per sample in `Salmon_Quants_Ultra/` |
| `run_hybrid_salmon.sh` | Hybrid STAR+Salmon pipeline; STAR physically aligns reads and emits a transcriptome BAM, which is quantified by Salmon; genome is preloaded into RAM (`--genomeLoad LoadAndExit`) and 4 jobs run concurrently | Paired-end `*_1/2.fastq.gz`, STAR index, transcriptome FASTA | `quant.sf` per sample in `Salmon_Quants_Hybrid/` |
| `run_pydeseq2_pipeline.py` | Aggregates Salmon `quant.sf` files into a gene counts matrix (via tx2gene mapping) and runs pyDESeq2 differential expression | Sample metadata CSV, tx2gene CSV, Salmon quants | Counts matrix, DESeq2 normalized counts, pairwise contrast CSV |
| `run_metaflux_optimized.R` | Computes metabolic fluxes with METAFlux using a parallelized sparse-matrix OSQP solver (avoids the original 2.1 GB dense-matrix conversion) | TPM matrix CSV, METAFlux model data | `flux_results_salmon.csv` |
| `compare_ryan_salmon.py` | Validation: compares Salmon `quant.sf` outputs against CLC baseline quants using a `sample_map.txt` mapping; computes Pearson r and R² on TPM and counts | Baseline quants + `sample_map.txt`, pipeline quants | Per-sample correlation table CSV |

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

- Tuned for one lab's hardware (tmpfs/RAM-disk staging, high thread counts).
- Tested on a single dataset (GSE267112).

## License

[Apache License 2.0](LICENSE)
