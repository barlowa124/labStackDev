#!/bin/bash
source /opt/conda/etc/profile.d/conda.sh
conda activate rnaseq

mkdir -p /mnt/c/Users/asdf/Downloads/Reference_Genome/STAR_Index
cd /mnt/c/Users/asdf/Downloads/Reference_Genome

# --- Adaptive Resource Allocation ---
TOTAL_CORES=$(nproc)
TOTAL_MEM_GB=$(awk '/MemTotal/ {printf "%.0f", $2/1024/1024}' /proc/meminfo)
USE_CORES=$((TOTAL_CORES > 1 ? TOTAL_CORES - 1 : 1))

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
STAR --runThreadN $USE_CORES \
     --runMode genomeGenerate \
     --genomeDir /mnt/c/Users/asdf/Downloads/Reference_Genome/STAR_Index \
     --genomeFastaFiles GRCh38.primary_assembly.genome.fa \
     --sjdbGTFfile gencode.v45.primary_assembly.annotation.gtf \
     --sjdbOverhang 149 \
     $SPARSE_FLAG

echo "Building RSEM index..."
rsem-prepare-reference --gtf gencode.v45.primary_assembly.annotation.gtf \
                       --num-threads $USE_CORES \
                       GRCh38.primary_assembly.genome.fa \
                       RSEM_Index/human

echo "Index generation complete!"
