# Stem Cell Lab RNA-seq Optimized Pipelines

This repository contains the optimized, benchmarked RNA-seq quantification pipelines developed for the GSE267112 dataset and future Stem Cell Lab Transcriptomics processing.

## 1. `run_salmon_ultra.sh`
**Ultra-Fast Pseudoalignment Pipeline (4 minutes per sample)**
- **Use Case:** Rapid, high-accuracy gene expression quantification for DESeq2/MetaFlux.
- **Features:** Skips physical mapping. Uses a highly optimized Expectation-Maximization probabilistic model to correct for GC-content, multi-mapping, and sequence biases.
- **Hardware Optimizations:** RAM-disk indexing (`tmpfs`), 12-thread parallel in-memory decompression (`pigz`), sequential SSD anti-thrashing, and maximized single-job multithreading (24 threads per instance). 
- **Accuracy:** Tested against original CLC baseline (~0.984 Pearson, ~0.968 R²).

## 2. `run_hybrid_salmon.sh`
**Standard Hybrid Pipeline (STAR + Salmon) (20 minutes per sample)**
- **Use Case:** Rigorous base-by-base physical alignment. Required when structural discovery (novel splice junctions, variant calling) is needed alongside quantification.
- **Features:** STAR generates a physical coordinate BAM file, which is immediately streamed via RAM directly into Salmon for simultaneous quantification.
- **Hardware Optimizations:** RAM-loaded genome (`--genomeLoad LoadAndExit`), RAM-pipe streaming (avoids writing intermediate BAM files to disk), multi-job parallel execution.

## 3. `build_index_adaptive.sh`
**Intelligent Reference Genome Builder**
- **Use Case:** Initializing the human reference genome (FASTA/GTF) for the pipelines.
- **Features:** Detects available RAM and dynamically adjusts `genomeSAindexNbases` to prevent out-of-memory crashes on hardware with <64GB RAM when building STAR indices.

## 4. `compare_ryan_salmon.py`
**Validation Script**
- **Use Case:** Verifies pipeline accuracy.
- **Features:** Parses raw CLC `.sf` quant outputs against new pipeline outputs, computing direct Pearson r and R² correlations across hundreds of thousands of transcripts. 
