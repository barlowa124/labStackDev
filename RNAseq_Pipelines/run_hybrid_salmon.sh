#!/bin/bash
source /opt/conda/etc/profile.d/conda.sh
conda activate salmon_env

# Ensure STAR is installed in this environment
if ! command -v STAR &> /dev/null; then
    echo "Installing STAR in salmon_env..."
    conda install -y -c bioconda star
fi

cd /mnt/c/Users/asdf/Downloads/GSE267112_FASTQ

STAR_INDEX="/mnt/c/Users/asdf/Downloads/Reference_Genome/star_index"
TRANSCRIPTOME_FA="/mnt/c/Users/asdf/Downloads/Reference_Genome/gencode.v45.transcripts.fa"
QUANTS_DIR="/mnt/c/Users/asdf/Downloads/Salmon_Quants_Hybrid"

rm -rf "$QUANTS_DIR"
mkdir -p "$QUANTS_DIR"

echo "Loading STAR genome into RAM to allow instant multi-job access..."
STAR --genomeLoad LoadAndExit --genomeDir "$STAR_INDEX"

# 32 Cores: 4 concurrent jobs.
CONCURRENT_JOBS=4
STAR_THREADS=4
SALMON_THREADS=4

echo "Starting Hybrid Pipeline: STAR Alignment mapped directly to Salmon EM Algorithm..."
start_time=$(date +%s)

cat << 'EOF' > /tmp/run_hybrid_single.sh
#!/bin/bash
source /opt/conda/etc/profile.d/conda.sh
conda activate salmon_env

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
cd /mnt/c/Users/asdf/Downloads/GSE267112_FASTQ
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
