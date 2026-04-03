import os
import sys
import pandas as pd
import numpy as np
from scipy.stats import pearsonr

ryan_dir = r"D:\Rao_Lab_Google_Drive_Downloads\Term Derived RNAseq"
our_dir = r"C:\Users\asdf\Downloads\Salmon_Quants"

# Wait for sample_map.txt
map_file = os.path.join(ryan_dir, "sample_map.txt")
if not os.path.exists(map_file):
    print("sample_map.txt not found yet.")
    sys.exit(0)

print(f"Reading {map_file}...")
with open(map_file, 'r') as f:
    lines = f.readlines()

mapping = {}
for line in lines:
    line = line.strip()
    if line and not line.startswith('#'):
        parts = line.split('\t')
        if len(parts) >= 2:
            srr_id = parts[0]
            ryan_name = parts[1]
            mapping[srr_id] = ryan_name

print(f"Found mapping for {len(mapping)} samples.")

correlations = []

for srr_id, ryan_name in mapping.items():
    ryan_quant = os.path.join(ryan_dir, f"{ryan_name}_quant", "quant.sf")
    our_quant = os.path.join(our_dir, srr_id, "quant.sf")
    
    if not os.path.exists(ryan_quant):
        print(f"Missing Ryan quant for {ryan_name} at {ryan_quant}")
        continue
    if not os.path.exists(our_quant):
        print(f"Missing our quant for {srr_id} at {our_quant}")
        continue
        
    df_ryan = pd.read_csv(ryan_quant, sep='\t')
    df_our = pd.read_csv(our_quant, sep='\t')
    
    # Ryan's 'Name' column contains full FASTA headers separated by pipes.
    # Extract the transcript ID (first element) to match our format.
    df_ryan['Name'] = df_ryan['Name'].apply(lambda x: x.split('|')[0])
    
    # Merge on Name
    merged = pd.merge(df_ryan, df_our, on='Name', suffixes=('_ryan', '_our'))
    
    # Compute correlation of TPM
    r_tpm, _ = pearsonr(merged['TPM_ryan'], merged['TPM_our'])
    r2_tpm = r_tpm ** 2
    
    # Compute correlation of NumReads (counts)
    r_counts, _ = pearsonr(merged['NumReads_ryan'], merged['NumReads_our'])
    
    correlations.append({
        'Sample (SRR)': srr_id,
        'Condition Name': ryan_name,
        'TPM Pearson r': r_tpm,
        'TPM R-squared': r2_tpm,
        'Counts Pearson r': r_counts,
        'Genes Compared': len(merged)
    })
    print(f"Compared {srr_id} vs {ryan_name}: TPM r={r_tpm:.4f}, R2={r2_tpm:.4f}")

if correlations:
    res_df = pd.DataFrame(correlations)
    print("\nFinal Summary:")
    print(res_df.to_string(index=False))
    res_df.to_csv(r"C:\Users\asdf\Downloads\Ryan_vs_20_Min_Salmon_Comparison.csv", index=False)
    print(f"\nAverage TPM Pearson r: {res_df['TPM Pearson r'].mean():.4f}")
    print(f"Average TPM R-squared: {res_df['TPM R-squared'].mean():.4f}")
else:
    print("No comparisons could be made.")
