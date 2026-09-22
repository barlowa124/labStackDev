#!/bin/bash
set -euo pipefail

if [ -f /opt/conda/etc/profile.d/conda.sh ]; then
    source /opt/conda/etc/profile.d/conda.sh
    conda activate salmon_env
fi

# Paths are configurable via environment variables (see README):
#   LABSTACK_DATA_DIR   directory of paired-end *_1/2.fastq.gz files (default ./data)
#   LABSTACK_INDEX_DIR  index root; expects star_index/ and gencode.v45.transcripts.fa
#                       (default ./index)
#   LABSTACK_OUT_DIR    output root; quants at <OUT_DIR>/Salmon_Quants_Hybrid (default ./results)
#   LABSTACK_THREADS    threads per STAR/Salmon job (default 4)
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

STAR_INDEX="$INDEX_DIR/star_index"
TRANSCRIPTOME_FA="$INDEX_DIR/gencode.v45.transcripts.fa"
if [ ! -d "$STAR_INDEX" ]; then
    echo "Error: STAR index '$STAR_INDEX' does not exist." >&2
    echo "Set LABSTACK_INDEX_DIR or build the index first." >&2
    exit 1
fi
if [ ! -f "$TRANSCRIPTOME_FA" ]; then
    echo "Error: transcriptome FASTA '$TRANSCRIPTOME_FA' does not exist." >&2
    exit 1
fi

QUANTS_DIR="$OUT_DIR/Salmon_Quants_Hybrid"

# Ensure STAR is installed in this environment
if command -v conda &> /dev/null && ! command -v STAR &> /dev/null; then
    echo "Installing STAR in salmon_env..."
    conda install -y -c bioconda star
fi

rm -rf "$QUANTS_DIR"
mkdir -p "$QUANTS_DIR"

echo "Loading STAR genome into RAM to allow instant multi-job access..."
STAR --genomeLoad LoadAndExit --genomeDir "$STAR_INDEX"

# 32 Cores: 4 concurrent jobs.
CONCURRENT_JOBS=4
STAR_THREADS="${LABSTACK_THREADS:-4}"
SALMON_THREADS="${LABSTACK_THREADS:-4}"

echo "Starting Hybrid Pipeline: STAR Alignment mapped directly to Salmon EM Algorithm..."
start_time=$(date +%s)

cat << 'EOF' > /tmp/run_hybrid_single.sh
#!/bin/bash
if [ -f /opt/conda/etc/profile.d/conda.sh ]; then
    source /opt/conda/etc/profile.d/conda.sh
    conda activate salmon_env
fi

# ALWAYS run from /tmp so STAR can create its FIFO files! (NTFS doesn't support FIFOs)
cd /tmp

f1="$1"
f2="$2"
base="$3"
STAR_INDEX="$4"
TRANSCRIPTOME_FA="$5"
QUANTS_DIR="$6"
STAR_THREADS="$7"
SALMON_THREADS="$8"

# We must give STAR a unique tmp directory per job!
UNIQUE_TMP="/tmp/star_tmp_${base}"
rm -rf "$UNIQUE_TMP"

echo "Processing $base (STAR mapping -> RAM Pipe -> Salmon quantification)..."

# STAR maps the reads to the transcriptome and pipes the BAM straight to stdout.
# Salmon immediately reads the incoming BAM stream (-a /dev/stdin) and calculates TPMs.
# We use zcat to decompress (pigz sometimes has quote parsing issues inside xargs/STAR)
STAR --runThreadN "$STAR_THREADS" \
     --genomeDir "$STAR_INDEX" \
     --genomeLoad LoadAndKeep \
     --readFilesIn "$f1" "$f2" \
     --readFilesCommand zcat \
     --outSAMtype BAM Unsorted \
     --quantMode TranscriptomeSAM \
     --outFileNamePrefix "/tmp/${base}_" \
     --outTmpDir "$UNIQUE_TMP" \
     --outFilterMultimapNmax 20 \
     --outSAMunmapped None

# STAR outputs the transcriptome BAM to /tmp/${base}_Aligned.toTranscriptome.out.bam (which is in RAM!)
# Now we feed this RAM-BAM directly into Salmon
echo "Running Salmon quantification on RAM-BAM..."
salmon quant -t "$TRANSCRIPTOME_FA" \
             -l A \
             -a "/tmp/${base}_Aligned.toTranscriptome.out.bam" \
             -p "$SALMON_THREADS" \
             -o "$QUANTS_DIR/${base}" \
             > "$QUANTS_DIR/${base}_salmon.log" 2>&1

exit_code=$?

# Immediately delete the RAM-BAM to free up memory
rm -f "/tmp/${base}_Aligned.toTranscriptome.out.bam" "/tmp/${base}_Aligned.out.bam"
rm -rf "$UNIQUE_TMP"
rm -f "/tmp/${base}_Log.progress.out" "/tmp/${base}_Log.final.out" "/tmp/${base}_Log.out" "/tmp/${base}_SJ.out.tab"

if [ $exit_code -ne 0 ]; then
    echo "Warning: Quantification failed on ${base} (Likely corrupted FASTQ)."
    rm -rf "$QUANTS_DIR/${base}"
else
    echo "Finished ${base}."
fi
EOF
chmod +x /tmp/run_hybrid_single.sh

# Resolve absolute paths before passing to the wrapper
cd "$DATA_DIR"
find "$(pwd)" -maxdepth 1 -name "*_1.fastq.gz" | while read f1; do
    f2="${f1/_1.fastq.gz/_2.fastq.gz}"
    base=$(basename "$f1" _1.fastq.gz)
    echo "$f1 $f2 $base $STAR_INDEX $TRANSCRIPTOME_FA $QUANTS_DIR $STAR_THREADS $SALMON_THREADS"
done | xargs -n 8 -P "$CONCURRENT_JOBS" bash /tmp/run_hybrid_single.sh

# Unload the genome from RAM
echo "Unloading genome from RAM..."
STAR --genomeLoad Remove --genomeDir "$STAR_INDEX"

end_time=$(date +%s)
duration=$((end_time - start_time))

echo "Hybrid STAR-Salmon Pipeline complete in $duration seconds!"
