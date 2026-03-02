# Setup METAFlux-Clean test environment using METAFlux package data
# Run once: Rscript setup_metaflux_test.R

library(METAFlux)
library(readxl)
library(writexl)

out_dir <- "C:/Users/asdf/Downloads/METAFlux-Clean"
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

# 1. Save human_gem, cell_medium
data(human_gem)
data(cell_medium)
save(human_gem, file = file.path(out_dir, "human_gem.rda"))

# 2. Create nutrient_lookup from human_gem (ID, EQUATION)
nutrient_lookup_files <- human_gem[, c("ID", "EQUATION")]
if (!"EQUATION" %in% colnames(nutrient_lookup_files)) {
  nutrient_lookup_files <- human_gem[, c(2, 4)]
  colnames(nutrient_lookup_files) <- c("ID", "EQUATION")
}
save(nutrient_lookup_files, file = file.path(out_dir, "nutrient_lookup_files.rda"))

# 3. Save cell_medium
save(cell_medium, file = file.path(out_dir, "cell_medium.rda"))

# 4. Create RNA-seq Excel from bulk_test_example
data(bulk_test_example)
expr_df <- as.data.frame(bulk_test_example)
expr_df <- cbind(Genes = rownames(expr_df), expr_df)
rownames(expr_df) <- NULL
writexl::write_xlsx(list(Sheet1 = expr_df), file.path(out_dir, "TPM_TA_vs_TUA.xlsx"))

# 5. Create data.R, calculate_score.R, optimization.R as thin wrappers to METAFlux
data_r <- 'calculate_reaction_score <- METAFlux::calculate_reaction_score
compute_flux <- METAFlux::compute_flux
'
writeLines(data_r, file.path(out_dir, "data.R"))

calc_r <- '# calculate_score.R - uses METAFlux
# calculate_reaction_score is loaded from data.R
'
writeLines(calc_r, file.path(out_dir, "calculate_score.R"))

opt_r <- '# optimization.R - compute_flux loaded from data.R
'
writeLines(opt_r, file.path(out_dir, "optimization.R"))

cat("Setup complete. Files in", out_dir, "\n")
cat("- human_gem.rda, cell_medium.rda, nutrient_lookup_files.rda\n")
cat("- TPM_TA_vs_TUA.xlsx\n")
cat("- data.R, calculate_score.R, optimization.R\n")
