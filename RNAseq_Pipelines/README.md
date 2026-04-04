# Stem Cell Lab RNA-seq Optimized Pipelines

This repository contains the optimized RNA-seq quantification pipelines developed for the GSE267112 dataset and future Stem Cell Lab Transcriptomics processing.

## 1. `run_salmon_pseudoalignment.sh`
**Direct Pseudoalignment Pipeline (4 minutes per sample)**
- **Use Case:** Efficient gene expression quantification for DESeq2/MetaFlux.
- **Features:** Utilizes a probabilistic Expectation-Maximization model to quantify transcripts, correcting for GC-content, multi-mapping, and sequence biases without requiring physical base alignment.
- **Hardware Optimizations:** RAM-disk indexing (`tmpfs`), parallel in-memory decompression (`pigz`), sequential I/O processing, and maximized single-job multithreading (24 threads per instance).
- **Accuracy:** Validated against original CLC baseline (0.984 Pearson, 0.968 R²).

## 2. `run_hybrid_salmon.sh`
**Standard Hybrid Pipeline (STAR + Salmon) (20 minutes per sample)**
- **Use Case:** Base-by-base physical alignment. Required when structural discovery (novel splice junctions, variant calling) is needed alongside quantification.
- **Features:** Generates a physical coordinate BAM file via STAR, which is streamed via RAM directly into Salmon for simultaneous quantification.
- **Hardware Optimizations:** RAM-loaded genome (`--genomeLoad LoadAndExit`), RAM-pipe streaming, and multi-job parallel execution.

## 3. `build_index_adaptive.sh`
**Adaptive Reference Genome Builder**
- **Use Case:** Initializing the human reference genome (FASTA/GTF) for the pipelines.
- **Features:** Detects available RAM and dynamically adjusts `genomeSAindexNbases` to prevent out-of-memory errors during STAR index generation.

## 4. `compare_ryan_salmon.py`
**Validation Script**
- **Use Case:** Verifies pipeline accuracy.
- **Features:** Parses raw CLC `.sf` outputs against new pipeline outputs, computing Pearson r and R² correlations. 
