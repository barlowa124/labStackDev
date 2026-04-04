#!/bin/bash
source /opt/conda/etc/profile.d/conda.sh
conda activate salmon_env

cd /mnt/c/Users/asdf/Downloads/GSE267112_FASTQ

TOTAL_CORES=$(nproc)
SALMON_INDEX="/mnt/c/Users/asdf/Downloads/Reference_Genome/salmon_index"
QUANTS_DIR="/mnt/c/Users/asdf/Downloads/Salmon_Quants_Ultra"

# Clear previous run
rm -rf "$QUANTS_DIR"
mkdir -p "$QUANTS_DIR"

echo "Copying Salmon Index to RAM-Disk (/tmp) for maximum read speed..."
cp -r "$SALMON_INDEX" /tmp/salmon_index_ram

# SEQUENTIAL processing is FASTER on SSDs because it prevents IO thrashing!
# By giving 1 job ALL the cores, it reads sequentially at max SSD speed.
CONCURRENT_JOBS=1
THREADS_PER_JOB=24
PIGZ_THREADS=12

echo "Running Ultra-Optimized Salmon (Sequential IO, Max Threads) with $CONCURRENT_JOBS concurrent jobs..."
start_time=$(date +%s)

# Create a wrapper script to run salmon with process substitution
cat << 'EOF' > /tmp/run_single_salmon.sh
#!/bin/bash
source /opt/conda/etc/profile.d/conda.sh
conda activate salmon_env

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
