# METAFlux analyzer module for Dr. Rao lab stack
# Converts expression matrix -> MRAS -> flux -> nutrient plot + pathway heatmap
# Includes metadata-driven column renaming and a telemetry/data-assessment suite.

suppressPackageStartupMessages({
  library(METAFlux)
  library(readxl)
  library(ggplot2)
  library(pheatmap)
  library(RColorBrewer)
  library(osqp)
  library(stringi)
  library(stringr)
  library(jsonlite)
})

`%||%` <- function(a, b) {
  if (is.null(a)) b else a
}

.validate_required_packages <- function() {
  required <- c("METAFlux", "readxl", "ggplot2", "pheatmap", "RColorBrewer", "osqp", "stringi", "stringr", "jsonlite")
  missing <- required[!vapply(required, requireNamespace, logical(1), quietly = TRUE)]
  if (length(missing) > 0) {
    stop(sprintf("Missing packages: %s", paste(missing, collapse = ", ")))
  }
}

.validate_files <- function(files) {
  files <- files[!is.na(files) & nzchar(files)]
  missing <- files[!file.exists(files)]
  if (length(missing) > 0) {
    stop(sprintf("Missing required files:\n%s", paste(missing, collapse = "\n")))
  }
}

read_sequence_data <- function(sequence_data_path, sheet = 1, gene_col = "Genes") {
  df <- readxl::read_excel(sequence_data_path, sheet = sheet)
  df <- as.data.frame(df)
  if (!(gene_col %in% colnames(df))) {
    stop(sprintf("Gene column '%s' not found in sequence data.", gene_col))
  }
  rownames(df) <- df[[gene_col]]
  df[[gene_col]] <- NULL
  df
}

apply_gene_knockout <- function(df, knockout_genes = character()) {
  if (length(knockout_genes) == 0) return(df)
  missing <- setdiff(knockout_genes, rownames(df))
  if (length(missing) > 0) {
    warning(sprintf("Knockout genes not found in matrix: %s", paste(missing, collapse = ", ")))
  }
  present <- intersect(knockout_genes, rownames(df))
  if (length(present) > 0) {
    df[present, ] <- 0
  }
  df
}

read_sample_mapping <- function(sample_metadata_path, metadata_columns = NULL) {
  if (is.null(sample_metadata_path) || !nzchar(sample_metadata_path)) {
    return(NULL)
  }
  if (!file.exists(sample_metadata_path)) {
    stop(sprintf("Sample metadata table not found: %s", sample_metadata_path))
  }

  map <- read.csv(sample_metadata_path, stringsAsFactors = FALSE, check.names = FALSE)
  if (nrow(map) == 0) stop("Sample metadata table is empty.")

  source_col_name <- metadata_columns$source %||% "source_col"
  normal_col_name <- metadata_columns$normal %||% "normal_col"
  ko_col_name <- metadata_columns$knockout %||% "knockout_col"

  required <- c(source_col_name, normal_col_name, ko_col_name)
  missing <- setdiff(required, colnames(map))
  if (length(missing) > 0) {
    stop(sprintf("Sample metadata table missing required columns: %s", paste(missing, collapse = ", ")))
  }

  list(
    table = map,
    source_col = source_col_name,
    normal_col = normal_col_name,
    knockout_col = ko_col_name
  )
}

rename_flux_columns_from_map <- function(flux_normal, flux_ko, sample_map_obj = NULL, normal_fallback = NULL, ko_fallback = NULL) {
  if (!is.null(sample_map_obj)) {
    map <- sample_map_obj$table
    source_col <- sample_map_obj$source_col
    normal_col <- sample_map_obj$normal_col
    knockout_col <- sample_map_obj$knockout_col

    normal_map <- setNames(as.character(map[[normal_col]]), as.character(map[[source_col]]))
    ko_map <- setNames(as.character(map[[knockout_col]]), as.character(map[[source_col]]))

    cn_normal <- colnames(flux_normal)
    cn_ko <- colnames(flux_ko)
    colnames(flux_normal) <- ifelse(cn_normal %in% names(normal_map), normal_map[cn_normal], cn_normal)
    colnames(flux_ko) <- ifelse(cn_ko %in% names(ko_map), ko_map[cn_ko], cn_ko)
    return(list(normal = flux_normal, knockout = flux_ko, used_mapping = TRUE))
  }

  if (!is.null(normal_fallback) && ncol(flux_normal) >= 1) colnames(flux_normal)[1] <- normal_fallback
  if (!is.null(ko_fallback) && ncol(flux_ko) >= 1) colnames(flux_ko)[1] <- ko_fallback
  list(normal = flux_normal, knockout = flux_ko, used_mapping = FALSE)
}

build_nutrient_reaction_map <- function(nutrients, lookup_table, reaction_override = list()) {
  equations <- as.character(lookup_table$EQUATION)
  ids <- as.character(lookup_table$ID)
  out <- setNames(vector("list", length(nutrients)), nutrients)
  for (n in nutrients) {
    idx <- grep(n, equations, ignore.case = TRUE)
    if (length(idx) == 0) {
      out[[n]] <- NA_character_
      next
    }
    rid <- ids[idx[1]]
    if (!is.null(reaction_override[[rid]])) {
      rid <- reaction_override[[rid]]
    }
    out[[n]] <- rid
  }
  out
}

get_nutrient_flux <- function(metabolite_name, flux_matrix, reaction_id) {
  if (is.na(reaction_id) || !nzchar(reaction_id)) {
    warning(sprintf("Metabolite not found in lookup: %s", metabolite_name))
    return(NULL)
  }
  if (!(reaction_id %in% rownames(flux_matrix))) {
    warning(sprintf("Reaction %s not found in flux results.", reaction_id))
    return(NULL)
  }

  flux_values <- flux_matrix[reaction_id, , drop = FALSE]
  sample_cols <- colnames(flux_matrix)
  df <- data.frame(
    Metabolite = metabolite_name,
    ReactionID = reaction_id,
    matrix(as.numeric(flux_values), nrow = 1),
    check.names = FALSE
  )
  colnames(df)[3:ncol(df)] <- sample_cols
  df
}

build_nutrient_flux_df <- function(nutrients, flux_results, lookup_table, reaction_override = list(), group_prefix = "Normal") {
  rxn_map <- build_nutrient_reaction_map(nutrients, lookup_table, reaction_override = reaction_override)
  nutrient_flux_list <- lapply(nutrients, function(n) {
    tryCatch(get_nutrient_flux(n, flux_results, reaction_id = rxn_map[[n]]), error = function(e) NULL)
  })
  nutrient_flux_list <- Filter(Negate(is.null), nutrient_flux_list)
  if (length(nutrient_flux_list) == 0) {
    stop("No nutrient flux rows generated. Check nutrient names and lookup file.")
  }
  out <- do.call(rbind, lapply(seq_along(nutrient_flux_list), function(i) {
    x <- nutrient_flux_list[[i]]
    x$Group <- sprintf("%s_%d", group_prefix, i)
    x
  }))
  out
}

build_long_nutrient_flux <- function(df, condition_name, selected_cols = NULL) {
  sample_cols <- setdiff(colnames(df), c("Metabolite", "ReactionID", "Group"))
  if (!is.null(selected_cols) && length(selected_cols) > 0) {
    sample_cols <- intersect(sample_cols, selected_cols)
  }
  if (length(sample_cols) == 0) {
    stop(sprintf("No sample columns available to plot for condition: %s", condition_name))
  }
  rows <- lapply(sample_cols, function(col_name) {
    data.frame(
      Metabolite = df$Metabolite,
      ReactionID = df$ReactionID,
      Sample = col_name,
      Flux = as.numeric(df[[col_name]]),
      Condition = condition_name,
      stringsAsFactors = FALSE
    )
  })
  do.call(rbind, rows)
}

plot_nutrient_flux <- function(normal_df, ko_df, title, y_limits = c(-0.03, 0.03), out_path = NULL, normal_cols = NULL, ko_cols = NULL) {
  normal_long <- build_long_nutrient_flux(normal_df, "Normal", selected_cols = normal_cols)
  ko_long <- build_long_nutrient_flux(ko_df, "Knockout", selected_cols = ko_cols)
  all_long <- rbind(normal_long, ko_long)

  p <- ggplot(all_long, aes(x = Metabolite, y = Flux, fill = Condition)) +
    geom_boxplot(alpha = 0.6, outlier.size = 0.9) +
    scale_fill_manual(values = c("Normal" = "blue", "Knockout" = "darkred")) +
    ggtitle(title) +
    xlab("Component") +
    ylab("Flux") +
    scale_y_continuous(limits = y_limits) +
    theme(axis.text.x = element_text(angle = 45, hjust = 1))

  if (!is.null(out_path)) {
    ggsave(out_path, p, width = 11, height = 6, dpi = 200)
  }
  p
}

compute_pathway_flux_df <- function(combined_flux_results, human_gem) {
  subsystems <- as.character(unlist(human_gem$SUBSYSTEM))
  n_flux <- nrow(combined_flux_results)
  if (length(subsystems) < n_flux) {
    stop("human_gem$SUBSYSTEM length is smaller than flux rows; cannot align pathways.")
  }
  subsystems <- subsystems[seq_len(n_flux)]
  valid <- !is.na(subsystems) & nzchar(subsystems)
  if (!any(valid)) {
    stop("No valid subsystem labels found for pathway summarization.")
  }

  abs_flux <- abs(as.matrix(combined_flux_results[valid, , drop = FALSE]))
  groups <- subsystems[valid]
  summed <- rowsum(abs_flux, group = groups, reorder = FALSE, na.rm = TRUE)
  counts <- as.numeric(table(groups))
  names(counts) <- names(table(groups))
  denom <- counts[rownames(summed)]
  averaged <- sweep(summed, 1, denom, "/", check.margin = FALSE)
  as.data.frame(averaged, check.names = FALSE)
}

plot_pathway_heatmap <- function(pathway_flux_df, top_n = 40, title = "Pathway Flux Heatmap", out_path = NULL, scale_mode = "row") {
  row_var <- apply(pathway_flux_df, 1, var, na.rm = TRUE)
  top_pathways <- names(sort(row_var, decreasing = TRUE))[seq_len(min(top_n, length(row_var)))]
  heat_colors <- colorRampPalette(brewer.pal(11, "RdBu"))(256)

  if (!is.null(out_path)) {
    png(out_path, width = 1300, height = 900, res = 140)
    on.exit(dev.off(), add = TRUE)
  }

  pheatmap(
    pathway_flux_df[top_pathways, , drop = FALSE],
    cluster_cols = FALSE,
    color = rev(heat_colors),
    fontsize_row = 8,
    scale = scale_mode,
    main = title
  )
}

matrix_stats <- function(x) {
  m <- as.matrix(x)
  vals <- as.numeric(m)
  vals <- vals[is.finite(vals)]
  if (length(vals) == 0) {
    return(list(rows = nrow(m), cols = ncol(m), na_fraction = 1, zero_fraction = NA, min = NA, max = NA, mean = NA, sd = NA, p05 = NA, p50 = NA, p95 = NA))
  }
  list(
    rows = nrow(m),
    cols = ncol(m),
    na_fraction = mean(!is.finite(as.numeric(m))),
    zero_fraction = mean(vals == 0),
    min = unname(min(vals)),
    max = unname(max(vals)),
    mean = unname(mean(vals)),
    sd = unname(sd(vals)),
    p05 = unname(quantile(vals, 0.05, na.rm = TRUE)),
    p50 = unname(quantile(vals, 0.50, na.rm = TRUE)),
    p95 = unname(quantile(vals, 0.95, na.rm = TRUE))
  )
}

build_pair_metrics <- function(flux_normal, flux_ko, sample_map_obj = NULL) {
  pair_df <- data.frame(normal_col = character(), knockout_col = character(), stringsAsFactors = FALSE)
  if (!is.null(sample_map_obj)) {
    map <- sample_map_obj$table
    ncol_name <- sample_map_obj$normal_col
    kcol_name <- sample_map_obj$knockout_col
    pair_df <- data.frame(normal_col = as.character(map[[ncol_name]]), knockout_col = as.character(map[[kcol_name]]), stringsAsFactors = FALSE)
    pair_df <- pair_df[pair_df$normal_col %in% colnames(flux_normal) & pair_df$knockout_col %in% colnames(flux_ko), , drop = FALSE]
  } else {
    n_pairs <- min(ncol(flux_normal), ncol(flux_ko))
    if (n_pairs > 0) {
      pair_df <- data.frame(
        normal_col = colnames(flux_normal)[seq_len(n_pairs)],
        knockout_col = colnames(flux_ko)[seq_len(n_pairs)],
        stringsAsFactors = FALSE
      )
    }
  }
  if (nrow(pair_df) == 0) return(data.frame())

  rows <- lapply(seq_len(nrow(pair_df)), function(i) {
    ncol_name <- pair_df$normal_col[i]
    kcol_name <- pair_df$knockout_col[i]
    x <- as.numeric(flux_normal[[ncol_name]])
    y <- as.numeric(flux_ko[[kcol_name]])
    valid <- is.finite(x) & is.finite(y)
    if (!any(valid)) {
      corr <- NA_real_
      mad <- NA_real_
    } else {
      corr <- suppressWarnings(cor(x[valid], y[valid], method = "pearson"))
      mad <- mean(abs(x[valid] - y[valid]), na.rm = TRUE)
    }
    data.frame(normal_col = ncol_name, knockout_col = kcol_name, pearson_r = corr, mean_abs_delta = mad, stringsAsFactors = FALSE)
  })
  do.call(rbind, rows)
}

write_markdown_assessment <- function(path, payload) {
  lines <- c(
    "# METAFlux Data Assessment Report",
    "",
    sprintf("- Generated: %s", payload$generated_at),
    sprintf("- Elapsed seconds: %.3f", payload$elapsed_seconds),
    sprintf("- Output dir: `%s`", payload$output_dir),
    "",
    "## Inputs",
    sprintf("- Sequence data: `%s`", payload$inputs$sequence_data_path),
    sprintf("- Knockout genes: %s", paste(payload$inputs$knockout_genes, collapse = ", ")),
    sprintf("- Nutrients: %s", paste(payload$inputs$nutrients, collapse = ", ")),
    "",
    "## Matrix Stats",
    sprintf("- Flux normal: rows=%s cols=%s mean=%.6f sd=%.6f", payload$matrix_stats$flux_normal$rows, payload$matrix_stats$flux_normal$cols, payload$matrix_stats$flux_normal$mean, payload$matrix_stats$flux_normal$sd),
    sprintf("- Flux knockout: rows=%s cols=%s mean=%.6f sd=%.6f", payload$matrix_stats$flux_knockout$rows, payload$matrix_stats$flux_knockout$cols, payload$matrix_stats$flux_knockout$mean, payload$matrix_stats$flux_knockout$sd),
    sprintf("- Pathway flux: rows=%s cols=%s mean=%.6f sd=%.6f", payload$matrix_stats$pathway_flux$rows, payload$matrix_stats$pathway_flux$cols, payload$matrix_stats$pathway_flux$mean, payload$matrix_stats$pathway_flux$sd),
    "",
    "## Data Quality Flags",
    sprintf("- Constant pathway rows: %s", payload$data_quality$constant_pathway_rows),
    sprintf("- High-NA pathway rows: %s", payload$data_quality$high_na_pathway_rows),
    sprintf("- Pair metrics available: %s", payload$data_quality$pair_metrics_rows),
    "",
    "## Files",
    sprintf("- `%s`", payload$files$nutrient_flux_plot),
    sprintf("- `%s`", payload$files$pathway_heatmap),
    sprintf("- `%s`", payload$files$flux_normal),
    sprintf("- `%s`", payload$files$flux_knockout),
    sprintf("- `%s`", payload$files$pathway_flux)
  )
  writeLines(lines, con = path)
}

generate_telemetry_and_assessment <- function(config, start_time, flux_normal, flux_ko, pathway_flux_df, pair_metrics, output_dir) {
  end_time <- Sys.time()
  elapsed <- as.numeric(difftime(end_time, start_time, units = "secs"))

  row_var <- apply(pathway_flux_df, 1, var, na.rm = TRUE)
  top_var <- sort(row_var, decreasing = TRUE)
  top_var <- head(top_var, min(20, length(top_var)))

  assessment <- list(
    generated_at = format(end_time, "%Y-%m-%d %H:%M:%S"),
    elapsed_seconds = round(elapsed, 3),
    output_dir = output_dir,
    inputs = list(
      sequence_data_path = config$sequence_data_path,
      knockout_genes = as.list(config$knockout_genes),
      nutrients = as.list(config$nutrients),
      sample_metadata_path = config$sample_metadata_path %||% ""
    ),
    matrix_stats = list(
      flux_normal = matrix_stats(flux_normal),
      flux_knockout = matrix_stats(flux_ko),
      pathway_flux = matrix_stats(pathway_flux_df)
    ),
    data_quality = list(
      constant_pathway_rows = sum(row_var == 0, na.rm = TRUE),
      high_na_pathway_rows = sum(apply(pathway_flux_df, 1, function(r) mean(is.na(r)) > 0.5)),
      pair_metrics_rows = nrow(pair_metrics)
    ),
    top_pathway_variance = as.list(top_var),
    pair_metrics = pair_metrics,
    files = list(
      nutrient_flux_plot = file.path(output_dir, "nutrient_flux_boxplot.png"),
      pathway_heatmap = file.path(output_dir, "pathway_flux_heatmap.png"),
      flux_normal = file.path(output_dir, "flux_results_normal.csv"),
      flux_knockout = file.path(output_dir, "flux_results_knockout.csv"),
      pathway_flux = file.path(output_dir, "pathway_flux_df.csv")
    )
  )

  summary_json <- file.path(output_dir, "analyzer_telemetry_summary.json")
  ai_json <- file.path(output_dir, "telemetry_ai_report_metaflux.json")
  team_md <- file.path(output_dir, "telemetry_team_report_metaflux.md")
  manifest_json <- file.path(output_dir, "metaflux_run_manifest.json")

  writeLines(jsonlite::toJSON(assessment, auto_unbox = TRUE, pretty = TRUE), con = summary_json)
  writeLines(jsonlite::toJSON(assessment, auto_unbox = TRUE, pretty = TRUE), con = ai_json)
  write_markdown_assessment(team_md, assessment)

  manifest <- list(
    generated_at = assessment$generated_at,
    elapsed_seconds = assessment$elapsed_seconds,
    output_dir = output_dir,
    files = assessment$files,
    telemetry_files = list(
      analyzer_telemetry_summary = summary_json,
      telemetry_ai_report = ai_json,
      telemetry_team_report = team_md
    )
  )
  writeLines(jsonlite::toJSON(manifest, auto_unbox = TRUE, pretty = TRUE), con = manifest_json)
}

run_metaflux_analyzer <- function(config) {
  start_time <- Sys.time()
  .validate_required_packages()

  required_keys <- c(
    "work_dir", "sequence_data_path", "human_gem_path", "cell_medium_path",
    "nutrient_lookup_path", "data_r_path", "calculate_score_r_path", "optimization_r_path",
    "output_dir", "knockout_genes", "nutrients"
  )
  missing_keys <- setdiff(required_keys, names(config))
  if (length(missing_keys) > 0) {
    stop(sprintf("Missing config keys: %s", paste(missing_keys, collapse = ", ")))
  }

  dir.create(config$output_dir, recursive = TRUE, showWarnings = FALSE)

  .validate_files(c(
    config$sequence_data_path, config$human_gem_path, config$cell_medium_path,
    config$nutrient_lookup_path, config$data_r_path, config$calculate_score_r_path, config$optimization_r_path,
    config$sample_metadata_path %||% ""
  ))

  source(config$data_r_path, local = TRUE)
  source(config$calculate_score_r_path, local = TRUE)
  source(config$optimization_r_path, local = TRUE)

  df <- read_sequence_data(config$sequence_data_path, sheet = config$sheet %||% 1)
  df_knockout <- apply_gene_knockout(df, config$knockout_genes)

  load(config$cell_medium_path)
  medium_to_use <- cell_medium
  load(config$human_gem_path)
  load(config$nutrient_lookup_path)

  gene_num <- METAFlux:::gene_num
  iso <- METAFlux:::iso
  multi_comp <- METAFlux:::multi_comp
  simple_comp <- METAFlux:::simple_comp
  Hgem <- METAFlux:::Hgem

  mras_scores <- calculate_reaction_score(df)
  mras_scores_ko <- calculate_reaction_score(df_knockout)

  flux_results <- compute_flux(mras = mras_scores, medium = medium_to_use)
  flux_results_ko <- compute_flux(mras = mras_scores_ko, medium = medium_to_use)

  metadata_columns <- if (!is.null(config$metadata_columns)) config$metadata_columns else list()
  sample_map <- read_sample_mapping(
    sample_metadata_path = config$sample_metadata_path %||% NULL,
    metadata_columns = metadata_columns
  )

  renamed <- rename_flux_columns_from_map(
    flux_normal = flux_results,
    flux_ko = flux_results_ko,
    sample_map_obj = sample_map,
    normal_fallback = config$normal_col_name %||% NULL,
    ko_fallback = config$ko_col_name %||% NULL
  )
  flux_results <- renamed$normal
  flux_results_ko <- renamed$knockout

  reaction_override <- if (!is.null(config$reaction_override)) config$reaction_override else list("HMR_9217" = "HMR_9286")

  normal_flux_df <- build_nutrient_flux_df(
    nutrients = config$nutrients,
    flux_results = flux_results,
    lookup_table = nutrient_lookup_files,
    reaction_override = reaction_override,
    group_prefix = "Normal"
  )
  ko_flux_df <- build_nutrient_flux_df(
    nutrients = config$nutrients,
    flux_results = flux_results_ko,
    lookup_table = nutrient_lookup_files,
    reaction_override = reaction_override,
    group_prefix = "Knockout"
  )

  barplot_obj <- plot_nutrient_flux(
    normal_df = normal_flux_df,
    ko_df = ko_flux_df,
    title = config$barplot_title %||% "Nutrient Flux Comparison",
    y_limits = config$y_limits %||% c(-0.03, 0.03),
    out_path = file.path(config$output_dir, "nutrient_flux_boxplot.png"),
    normal_cols = config$plot_normal_cols %||% NULL,
    ko_cols = config$plot_ko_cols %||% NULL
  )

  combined_flux_results <- cbind(flux_results, flux_results_ko)
  pathway_flux_df <- compute_pathway_flux_df(combined_flux_results, human_gem)

  write.csv(flux_results, file.path(config$output_dir, "flux_results_normal.csv"), row.names = TRUE)
  write.csv(flux_results_ko, file.path(config$output_dir, "flux_results_knockout.csv"), row.names = TRUE)
  write.csv(pathway_flux_df, file.path(config$output_dir, "pathway_flux_df.csv"), row.names = TRUE)

  plot_pathway_heatmap(
    pathway_flux_df = pathway_flux_df,
    top_n = config$top_pathways_n %||% 40,
    title = config$heatmap_title %||% "Knockout Pathway Heatmap",
    out_path = file.path(config$output_dir, "pathway_flux_heatmap.png"),
    scale_mode = config$heatmap_scale %||% "row"
  )

  pair_metrics <- build_pair_metrics(flux_results, flux_results_ko, sample_map_obj = sample_map)
  if (isTRUE(config$enable_assessment_suite %||% TRUE)) {
    generate_telemetry_and_assessment(
      config = config,
      start_time = start_time,
      flux_normal = flux_results,
      flux_ko = flux_results_ko,
      pathway_flux_df = pathway_flux_df,
      pair_metrics = pair_metrics,
      output_dir = config$output_dir
    )
  }

  list(
    barplot = barplot_obj,
    normal_flux_df = normal_flux_df,
    knockout_flux_df = ko_flux_df,
    pathway_flux_df = pathway_flux_df,
    pair_metrics = pair_metrics,
    used_metadata_mapping = renamed$used_mapping
  )
}
