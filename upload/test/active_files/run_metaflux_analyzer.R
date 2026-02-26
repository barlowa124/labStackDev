#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)

config_path <- NULL
for (i in seq_along(args)) {
  if (args[[i]] == "--config" && i < length(args)) {
    config_path <- args[[i + 1]]
    break
  }
}

if (is.null(config_path)) {
  stop("Usage: Rscript run_metaflux_analyzer.R --config <path-to-config.json>")
}

if (!file.exists(config_path)) {
  stop(sprintf("Config file not found: %s", config_path))
}

source("metaflux_analyzer.R", local = TRUE)

cfg <- jsonlite::fromJSON(config_path, simplifyVector = TRUE)
if (!is.list(cfg)) {
  stop("Config JSON did not parse into a list.")
}

result <- run_metaflux_analyzer(cfg)
cat(jsonlite::toJSON(list(ok = TRUE, output_dir = cfg$output_dir), auto_unbox = TRUE), "\n")
