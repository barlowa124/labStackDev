import os

import pandas as pd
from pydeseq2.dds import DeseqDataSet
from pydeseq2.ds import DeseqStats

meta_path = r"C:\Users\asdf\Documents\GEO_Submission_Metadata.csv"
tx2gene_path = r"C:\Users\asdf\Downloads\Reference_Genome\salmon_tx2gene.csv"
quants_dir = r"C:\Users\asdf\Downloads\Salmon_Quants_Ultra"

metadata = pd.read_csv(meta_path)
metadata.set_index("Sample_ID", inplace=True)

tx2gene = pd.read_csv(tx2gene_path)

counts = {}

for sample_id, row in metadata.iterrows():
    srr = row["SRR_Accession"]
    quant_file = os.path.join(quants_dir, srr, "quant.sf")
    df = pd.read_csv(quant_file, sep="\t")
    # Our names might have version numbers, or tx2gene might. Let's ensure match.
    # In Salmon quant.sf: Name column.
    # Let's try direct merge.
    df_merged = pd.merge(df, tx2gene, left_on="Name", right_on="Transcript", how="inner")

    # Sum NumReads
    gene_counts = df_merged.groupby("Gene")["NumReads"].sum().round().astype(int)
    counts[sample_id] = gene_counts

# Convert to dataframe
counts_df = pd.DataFrame(counts).fillna(0).astype(int)

# PyDESeq2 expects genes as columns, samples as rows.
counts_df_t = counts_df.T

# Ensure indices match
metadata = metadata.loc[counts_df_t.index]

# Filter out genes with zero variance / 0 total counts
counts_df_t = counts_df_t.loc[:, (counts_df_t != 0).any(axis=0)]

print("Initializing DESeq2...")
dds = DeseqDataSet(
    counts=counts_df_t,
    metadata=metadata,
    design_factors="Condition"
)

print("Fitting DESeq2 model...")
dds.deseq2()

# Save normalized counts
print("Saving normalized counts...")
normalized_counts = pd.DataFrame(dds.layers["normed_counts"], index=dds.obs_names, columns=dds.var_names)
normalized_counts.T.to_csv("DESeq2_Normalized_Counts.csv")

# Save raw counts matrix
counts_df.to_csv("Salmon_Counts_Matrix_Symbols_Ultra.csv")

# Optional: Run a pairwise test
print("Calculating stats for female TSCM vs female TA...")
stat_res = DeseqStats(dds, contrast=["Condition", "female_TSCM", "female_TA"])
stat_res.summary()
res_df = stat_res.results_df
res_df.to_csv("DESeq2_female_TSCM_vs_female_TA.csv")

print("Done. All DESeq2 outputs generated.")
