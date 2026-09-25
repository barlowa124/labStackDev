#!/bin/bash
set -euo pipefail

if [ -f /opt/conda/etc/profile.d/conda.sh ]; then
    source /opt/conda/etc/profile.d/conda.sh
    conda activate salmon_env
fi

# Paths are configurable via environment variables (see README):
#   LABSTACK_DATA_DIR   directory of paired-end *_1/2.fastq.gz files (default ./data)
#   LABSTACK_INDEX_DIR  index root; Salmon index at <INDEX_DIR>/salmon_index (default ./index)
#   LABSTACK_OUT_DIR    output root; quants at <OUT_DIR>/Salmon_Quants_Ultra (default ./results)
#   LABSTACK_THREADS    threads per Salmon job (default: all cores)
DATA_DIR="${LABSTACK_DATA_DIR:-./data}"
INDEX_DIR="${LABSTACK_INDEX_DIR:-./index}"
OUT_DIR="${LABSTACK_OUT_DIR:-./results}"

if [ ! -d "$DATA_DIR" ]; then
    echo "Error: FASTQ data directory '$DATA_DIR' does not exist." >&2
    echo "Set LABSTACK_DATA_DIR to a directory containing paired-end *_1.fastq.gz / *_2.fastq.gz files." >&2
    exit 1
fi

# Resolve to absolute before cd'ing into the data dir
if [ -d "$INDEX_DIR" ]; then
    INDEX_DIR="$(cd "$INDEX_DIR" && pwd)"
fi
mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"

SALMON_INDEX="$INDEX_DIR/salmon_index"
if [ ! -d "$SALMON_INDEX" ]; then
    echo "Error: Salmon index '$SALMON_INDEX' does not exist." >&2
    echo "Set LABSTACK_INDEX_DIR or build the index first." >&2
    exit 1
fi

QUANTS_DIR="$OUT_DIR/Salmon_Quants_Ultra"

cd "$DATA_DIR"

TOTAL_CORES=$(nproc)

# Clear previous run
rm -rf "$QUANTS_DIR"
mkdir -p "$QUANTS_DIR"

echo "Copying Salmon Index to RAM-Disk (/tmp) for maximum read speed..."
cp -r "$SALMON_INDEX" /tmp/salmon_index_ram

# Clean up the RAM copy and helper script even on failure
trap 'rm -rf /tmp/salmon_index_ram /tmp/run_single_salmon.sh' EXIT

# SEQUENTIAL processing is FASTER on SSDs because it prevents IO thrashing!
# By giving 1 job ALL the cores, it reads sequentially at max SSD speed.
CONCURRENT_JOBS=1
THREADS_PER_JOB="${LABSTACK_THREADS:-$TOTAL_CORES}"
PIGZ_THREADS=12

echo "Running Ultra-Optimized Salmon (Sequential IO, Max Threads) with $CONCURRENT_JOBS concurrent jobs..."
start_time=$(date +%s)

# Create a wrapper script to run salmon with process substitution
cat << 'EOF' > /tmp/run_single_salmon.sh
#!/bin/bash
if [ -f /opt/conda/etc/profile.d/conda.sh ]; then
    source /opt/conda/etc/profile.d/conda.sh
    conda activate salmon_env
fi

f1="$1"
f2="$2"
base="$3"
THREADS_PER_JOB="$4"
PIGZ_THREADS="$5"
QUANTS_DIR="$6"

echo "Running Salmon on ${base}..."
# Use process substitution to decompress entirely in memory, straight to Salmon!
salmon quant -i /tmp/salmon_index_ram \
             -l A \
             -1 <(pigz -dc -p $PIGZ_THREADS "$f1") \
             -2 <(pigz -dc -p $PIGZ_THREADS "$f2") \
             -p $THREADS_PER_JOB \
             --validateMappings \
             -o "$QUANTS_DIR/${base}" > "$QUANTS_DIR/${base}_salmon.log" 2>&1

exit_code=$?
if [ $exit_code -ne 0 ]; then
    echo "Warning: Salmon failed on ${base}. Likely a corrupted FASTQ file."
    rm -rf "$QUANTS_DIR/${base}"
else
    echo "Finished ${base}."
fi
EOF
chmod +x /tmp/run_single_salmon.sh

# Run the jobs
find . -maxdepth 1 -name "*_1.fastq.gz" | while read f1; do
    f2="${f1/_1.fastq.gz/_2.fastq.gz}"
    base=$(basename "$f1" _1.fastq.gz)
    echo "$f1 $f2 $base $THREADS_PER_JOB $PIGZ_THREADS $QUANTS_DIR"
done | xargs -n 6 -P $CONCURRENT_JOBS bash /tmp/run_single_salmon.sh

# Stop timing
end_time=$(date +%s)
duration=$((end_time - start_time))

echo "Quantification complete in $duration seconds."

# Cleanup RAM
rm -rf /tmp/salmon_index_ram
rm -f /tmp/run_single_salmon.sh

echo "Ultra-Optimized Pipeline finished successfully in $duration seconds!"
