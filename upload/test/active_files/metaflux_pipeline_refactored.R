suppressPackageStartupMessages({
  library(readxl)
  library(ggplot2)
  library(pheatmap)
  library(RColorBrewer)
  library(jsonlite)
  library(yaml)
  library(stringi)
  library(stringr)
  library(osqp)
})

required_packages <- c("METAFlux", "readxl", "ggplot2", "pheatmap", "RColorBrewer", "jsonlite", "yaml", "stringi", "stringr", "osqp")
missing_packages <- required_packages[!vapply(required_packages, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing_packages) > 0) {
  stop(sprintf("Missing required packages: %s", paste(missing_packages, collapse = ", ")))
}

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) {
  stop("Usage: Rscript metaflux_pipeline_refactored.R <config.yaml>")
}

config_path <- normalizePath(args[1], mustWork = TRUE)
cfg <- yaml::read_yaml(config_path)

must_exist <- function(path, name) {
  if (!file.exists(path)) {
    stop(sprintf("%s not found: %s", name, path))
  }
  normalizePath(path, mustWork = TRUE)
}

project_root <- must_exist(cfg$paths$project_root, "project_root")
rnaseq_file <- must_exist(cfg$paths$rnaseq_file, "rnaseq_file")
metadata_file <- if (!is.null(cfg$paths$sample_metadata_file) && nzchar(cfg$paths$sample_metadata_file)) cfg$paths$sample_metadata_file else NULL
if (!is.null(metadata_file) && file.exists(metadata_file)) {
  metadata_file <- normalizePath(metadata_file, mustWork = TRUE)
}

human_gem_path <- must_exist(file.path(project_root, cfg$paths$human_gem_file), "human_gem")
cell_medium_path <- must_exist(file.path(project_root, cfg$paths$cell_medium_file), "cell_medium")
nutrient_lookup_path <- must_exist(file.path(project_root, cfg$paths$nutrient_lookup_file), "nutrient_lookup")

data_r <- must_exist(file.path(project_root, cfg$paths$data_r), "data.R")
calculate_score_r <- must_exist(file.path(project_root, cfg$paths$calculate_score_r), "calculate_score.R")
optimization_r <- must_exist(file.path(project_root, cfg$paths$optimization_r), "optimization.R")

output_dir <- cfg$output$output_dir
if (is.null(output_dir) || !nzchar(output_dir)) {
  output_dir <- file.path(project_root, "runs", format(Sys.time(), "%Y%m%d_%H%M%S"))
}
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
output_dir <- normalizePath(output_dir, winslash = "/", mustWork = TRUE)

source(data_r)
source(calculate_score_r)
source(optimization_r)

expr_df <- readxl::read_excel(rnaseq_file, sheet = cfg$input$sheet_index)
expr_df <- as.data.frame(expr_df)

if (!(cfg$input$gene_column %in% colnames(expr_df))) {
  stop(sprintf("Gene column '%s' not found", cfg$input$gene_column))
}

gene_col <- cfg$input$gene_column
expr_df[[gene_col]] <- as.character(expr_df[[gene_col]])
if (any(is.na(expr_df[[gene_col]]) | trimws(expr_df[[gene_col]]) == "")) {
  stop("Gene column contains empty values")
}
if (any(duplicated(expr_df[[gene_col]]))) {
  stop("Gene column contains duplicates")
}

rownames(expr_df) <- expr_df[[gene_col]]
expr_df[[gene_col]] <- NULL

for (col_name in colnames(expr_df)) {
  expr_df[[col_name]] <- suppressWarnings(as.numeric(expr_df[[col_name]]))
}
if (anyNA(expr_df)) {
  stop("Expression matrix contains NA after numeric conversion; clean input first")
}
if (any(expr_df < 0)) {
  stop("Expression matrix contains negative values")
}

if (nrow(expr_df) < cfg$input$min_genes) {
  stop(sprintf("Too few genes (%d). Minimum required is %d", nrow(expr_df), cfg$input$min_genes))
}

load(human_gem_path)
load(cell_medium_path)
load(nutrient_lookup_path)

if (!exists("cell_medium")) {
  stop("cell_medium object not found in medium RDA")
}
if (!exists("human_gem")) {
  stop("human_gem object not found in human_gem RDA")
}
if (!exists("nutrient_lookup_files")) {
  stop("nutrient_lookup_files object not found in nutrient_lookup RDA")
}

medium_to_use <- cell_medium
if (!is.null(cfg$model$medium_profile_name) && !identical(cfg$model$medium_profile_name, "cell_medium")) {
  if (exists(cfg$model$medium_profile_name)) {
    medium_to_use <- get(cfg$model$medium_profile_name)
  } else {
    stop(sprintf("Configured medium profile '%s' does not exist", cfg$model$medium_profile_name))
  }
}

knockout_genes <- cfg$model$knockout_genes
if (is.null(knockout_genes)) knockout_genes <- character(0)
knockout_genes <- unique(as.character(knockout_genes))
missing_knockout_genes <- knockout_genes[!knockout_genes %in% rownames(expr_df)]
if (length(missing_knockout_genes) > 0) {
  warning(sprintf("Knockout genes not in matrix: %s", paste(missing_knockout_genes, collapse = ", ")))
}

expr_knockout <- expr_df
present_kos <- knockout_genes[knockout_genes %in% rownames(expr_knockout)]
if (length(present_kos) > 0) {
  expr_knockout[present_kos, ] <- 0
}

mras_normal <- calculate_reaction_score(expr_df)
mras_knockout <- calculate_reaction_score(expr_knockout)

flux_normal <- compute_flux(mras = mras_normal, medium = medium_to_use)
flux_knockout <- compute_flux(mras = mras_knockout, medium = medium_to_use)

if (!is.null(cfg$output$knockout_suffix) && nzchar(cfg$output$knockout_suffix)) {
  ko_suffix <- cfg$output$knockout_suffix
} else {
  ko_suffix <- " (ko)"
}
colnames(flux_knockout) <- paste0(colnames(flux_knockout), ko_suffix)

reaction_override <- cfg$model$reaction_overrides
if (is.null(reaction_override)) reaction_override <- list()

get_nutrient_flux <- function(metabolite_name, flux_matrix, lookup_table, overrides) {
  id_row <- grep(metabolite_name, lookup_table$EQUATION, ignore.case = TRUE)
  if (length(id_row) == 0) return(NULL)
  reaction_id <- lookup_table$ID[id_row[1]]
  if (!is.null(overrides[[reaction_id]]) && nzchar(overrides[[reaction_id]])) {
    reaction_id <- overrides[[reaction_id]]
  }
  if (!reaction_id %in% rownames(flux_matrix)) return(NULL)
  flux_values <- flux_matrix[reaction_id, , drop = FALSE]
  out <- data.frame(
    Metabolite = metabolite_name,
    ReactionID = reaction_id,
    t(as.numeric(flux_values)),
    check.names = FALSE
  )
  colnames(out)[3:ncol(out)] <- colnames(flux_matrix)
  out
}

nutrients <- cfg$model$nutrients_to_plot
if (is.null(nutrients) || length(nutrients) == 0) {
  nutrients <- c("glucose", "glutamine", "lactate", "O2", "CO2", "pyruvate", "citrate", "acetate")
}

nutrient_normal <- Filter(Negate(is.null), lapply(nutrients, function(n) get_nutrient_flux(n, flux_normal, nutrient_lookup_files, reaction_override)))
nutrient_knockout <- Filter(Negate(is.null), lapply(nutrients, function(n) get_nutrient_flux(n, flux_knockout, nutrient_lookup_files, reaction_override)))

combined_flux <- cbind(flux_normal, flux_knockout)
all_pathways <- unique(unlist(human_gem$SUBSYSTEM))
pathway_scores <- list()
for (path in all_pathways) {
  idx <- which(unlist(human_gem$SUBSYSTEM) == path)
  if (length(idx) == 0) next
  avg_flux <- sapply(seq_len(ncol(combined_flux)), function(sample_index) {
    mean(abs(combined_flux[idx, sample_index]), na.rm = TRUE)
  })
  pathway_scores[[path]] <- avg_flux
}

pathway_flux_df <- as.data.frame(do.call(rbind, pathway_scores))
colnames(pathway_flux_df) <- colnames(combined_flux)

row_var <- apply(pathway_flux_df, 1, var, na.rm = TRUE)
top_n <- cfg$output$top_pathways
if (is.null(top_n) || !is.numeric(top_n) || top_n < 1) top_n <- 40
top_pathways <- names(sort(row_var, decreasing = TRUE, na.last = TRUE))[seq_len(min(top_n, length(row_var)))]
if (length(top_pathways) == 0) stop("No pathways available for heatmap")

heat_colors <- colorRampPalette(brewer.pal(11, "RdBu"))(256)
png(filename = file.path(output_dir, "pathway_heatmap.png"), width = 1800, height = 1400, res = 220)
pheatmap(pathway_flux_df[top_pathways, , drop = FALSE],
         cluster_cols = FALSE,
         color = rev(heat_colors),
         fontsize_row = 8,
         scale = "row",
         main = if (is.null(cfg$output$heatmap_title)) "METAFlux Pathway Activity" else cfg$output$heatmap_title)
dev.off()

normal_nutrient_df <- if (length(nutrient_normal) > 0) do.call(rbind, nutrient_normal) else NULL
knockout_nutrient_df <- if (length(nutrient_knockout) > 0) do.call(rbind, nutrient_knockout) else NULL

if (!is.null(normal_nutrient_df) && !is.null(knockout_nutrient_df)) {
  normal_col <- cfg$output$normal_condition_column
  ko_col <- cfg$output$knockout_condition_column
  if (is.null(normal_col) || !normal_col %in% colnames(normal_nutrient_df)) {
    normal_col <- colnames(normal_nutrient_df)[3]
  }
  if (is.null(ko_col) || !ko_col %in% colnames(knockout_nutrient_df)) {
    ko_col <- colnames(knockout_nutrient_df)[3]
  }

  p <- ggplot() +
    geom_boxplot(data = normal_nutrient_df, aes(x = Metabolite, y = .data[[normal_col]]), fill = "steelblue", color = "steelblue", alpha = 0.5) +
    geom_boxplot(data = knockout_nutrient_df, aes(x = Metabolite, y = .data[[ko_col]]), fill = "firebrick", color = "firebrick", alpha = 0.5) +
    ggtitle(if (is.null(cfg$output$nutrient_plot_title) || !nzchar(cfg$output$nutrient_plot_title)) "Nutrient Flux Comparison" else cfg$output$nutrient_plot_title) +
    xlab("Metabolite") +
    ylab("Flux") +
    theme(axis.text.x = element_text(angle = 45, hjust = 1))

  if (!is.null(cfg$output$flux_limits) && length(cfg$output$flux_limits) == 2) {
    p <- p + scale_y_continuous(limits = c(as.numeric(cfg$output$flux_limits[[1]]), as.numeric(cfg$output$flux_limits[[2]])))
  }
  ggsave(file.path(output_dir, "nutrient_flux_boxplot.png"), p, width = 12, height = 7, dpi = 200)
}

write.csv(flux_normal, file.path(output_dir, "flux_normal.csv"), row.names = TRUE)
write.csv(flux_knockout, file.path(output_dir, "flux_knockout.csv"), row.names = TRUE)
write.csv(combined_flux, file.path(output_dir, "flux_combined.csv"), row.names = TRUE)
write.csv(pathway_flux_df, file.path(output_dir, "pathway_flux.csv"), row.names = TRUE)
if (!is.null(normal_nutrient_df)) write.csv(normal_nutrient_df, file.path(output_dir, "nutrient_flux_normal.csv"), row.names = FALSE)
if (!is.null(knockout_nutrient_df)) write.csv(knockout_nutrient_df, file.path(output_dir, "nutrient_flux_knockout.csv"), row.names = FALSE)

run_metadata <- list(
  timestamp = format(Sys.time(), "%Y-%m-%d %H:%M:%S %Z"),
  config_path = config_path,
  project_root = project_root,
  rnaseq_file = rnaseq_file,
  metadata_file = metadata_file,
  output_dir = output_dir,
  n_genes = nrow(expr_df),
  n_samples = ncol(expr_df),
  knockout_genes = knockout_genes,
  missing_knockout_genes = missing_knockout_genes,
  medium_profile = cfg$model$medium_profile_name,
  nutrients_plotted = nutrients,
  top_pathways = length(top_pathways)
)
writeLines(jsonlite::toJSON(run_metadata, pretty = TRUE, auto_unbox = TRUE), file.path(output_dir, "run_metadata.json"))

if (!is.null(cfg$model$sensitivity_medium_profiles) && length(cfg$model$sensitivity_medium_profiles) > 0) {
  sensitivity_results <- list()
  for (medium_name in cfg$model$sensitivity_medium_profiles) {
    if (!exists(medium_name)) next
    medium_obj <- get(medium_name)
    flux_sens <- compute_flux(mras = mras_normal, medium = medium_obj)
    out_file <- file.path(output_dir, paste0("flux_sensitivity_", medium_name, ".csv"))
    write.csv(flux_sens, out_file, row.names = TRUE)
    sensitivity_results[[medium_name]] <- list(file = out_file, n_reactions = nrow(flux_sens), n_samples = ncol(flux_sens))
  }
  writeLines(jsonlite::toJSON(sensitivity_results, pretty = TRUE, auto_unbox = TRUE), file.path(output_dir, "sensitivity_summary.json"))
}

message(sprintf("Pipeline complete. Outputs: %s", output_dir))
