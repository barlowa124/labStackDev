#!/bin/bash
set -euo pipefail

if [ -f /opt/conda/etc/profile.d/conda.sh ]; then
    source /opt/conda/etc/profile.d/conda.sh
    conda activate rnaseq
fi

# Paths are configurable via environment variables (see README):
#   LABSTACK_DATA_DIR   directory containing GRCh38.primary_assembly.genome.fa
#                       and gencode.v45.primary_assembly.annotation.gtf (default ./data)
#   LABSTACK_INDEX_DIR  output root for the generated indexes (default ./index)
#   LABSTACK_THREADS    threads to use (default: all cores minus one)
DATA_DIR="${LABSTACK_DATA_DIR:-./data}"
INDEX_DIR="${LABSTACK_INDEX_DIR:-./index}"

if [ ! -d "$DATA_DIR" ]; then
    echo "Error: reference data directory '$DATA_DIR' does not exist." >&2
    echo "Set LABSTACK_DATA_DIR to a directory containing GRCh38.primary_assembly.genome.fa and gencode.v45.primary_assembly.annotation.gtf." >&2
    exit 1
fi

# Resolve to absolute before cd'ing into the data dir
mkdir -p "$INDEX_DIR"
INDEX_DIR="$(cd "$INDEX_DIR" && pwd)"
STAR_INDEX_DIR="$INDEX_DIR/STAR_Index"
mkdir -p "$STAR_INDEX_DIR"
cd "$DATA_DIR"

# --- Adaptive Resource Allocation ---
TOTAL_CORES=$(nproc)
TOTAL_MEM_GB=$(awk '/MemTotal/ {printf "%.0f", $2/1024/1024}' /proc/meminfo)
USE_CORES="${LABSTACK_THREADS:-$((TOTAL_CORES > 1 ? TOTAL_CORES - 1 : 1))}"

echo "Detected $TOTAL_CORES cores and ${TOTAL_MEM_GB}GB RAM."

SPARSE_FLAG=""
# If RAM is less than 32GB, use sparse index to avoid crashing
if [ "$TOTAL_MEM_GB" -lt 32 ]; then
    echo "Low RAM detected. Using --genomeSAsparseD 2 to halve memory requirements."
    SPARSE_FLAG="--genomeSAsparseD 2"
else
    echo "Sufficient RAM detected. Building full standard index."
fi

echo "Building STAR index..."
STAR --runThreadN "$USE_CORES" \
     --runMode genomeGenerate \
     --genomeDir "$STAR_INDEX_DIR" \
     --genomeFastaFiles GRCh38.primary_assembly.genome.fa \
     --sjdbGTFfile gencode.v45.primary_assembly.annotation.gtf \
     --sjdbOverhang 149 \
     $SPARSE_FLAG

echo "Building RSEM index..."
rsem-prepare-reference --gtf gencode.v45.primary_assembly.annotation.gtf \
                       --num-threads "$USE_CORES" \
                       GRCh38.primary_assembly.genome.fa \
                       "$INDEX_DIR/RSEM_Index/human"

echo "Index generation complete!"
