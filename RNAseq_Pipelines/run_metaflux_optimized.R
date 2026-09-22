library(METAFlux)
library(data.table)
library(doParallel)
library(foreach)
library(Matrix)
library(osqp)

# Paths are configurable via environment variables (see README):
#   LABSTACK_METAFLUX_DIR  directory containing the METAFlux sources
#                         (data.R, calculate_score.R, optimization.R, *.rda)
#   LABSTACK_DATA_DIR      directory containing the TPM matrix CSV (default ./data)
metaflux_dir <- Sys.getenv("LABSTACK_METAFLUX_DIR", "./METAFlux")
data_dir <- Sys.getenv("LABSTACK_DATA_DIR", "./data")
if (!dir.exists(metaflux_dir)) {
    stop(paste0("METAFlux directory '", metaflux_dir,
                "' does not exist. Set LABSTACK_METAFLUX_DIR."))
}
sequenceData <- file.path(data_dir, "Salmon_TPM_Matrix_Symbols_Ultra.csv")
if (!file.exists(sequenceData)) {
    stop(paste0("TPM matrix '", sequenceData,
                "' does not exist. Set LABSTACK_DATA_DIR."))
}

setwd(metaflux_dir)

source("data.R")
source("calculate_score.R")
source("optimization.R")

cat("Loading Data...\n")
df <- fread(sequenceData, data.table = FALSE)

# Drop any duplicated rows or NA
cat("Cleaning Data...\n")
df <- df[!duplicated(df$GeneSymbol), ]
df <- df[!is.na(df$GeneSymbol), ]

rownames(df) <- df$GeneSymbol
df$GeneSymbol <- NULL

cat("Loading Models...\n")
load("cell_medium.rda")
medium_to_use <- cell_medium
load("human_gem.rda")

library(stringi)
library(stringr)

gene_num     <- METAFlux:::gene_num
iso          <- METAFlux:::iso
multi_comp   <- METAFlux:::multi_comp
simple_comp  <- METAFlux:::simple_comp
Hgem         <- METAFlux:::Hgem

cat("Calculating MRAS Scores...\n")
mras_scores <- calculate_reaction_score(df)

cat("Setting up High-Speed Sparse Matrices for OSQP Solver...\n")
# --- MASSIVE OPTIMIZATION: Sparse Matrix Setup ---
# The original compute_flux forces a 2.1 GB dense matrix conversion `as.matrix(rbind(Hgem$S, P))`.
# This is incredibly slow and hogs RAM. OSQP is designed for sparse matrices natively.
P_sparse <- Matrix::Diagonal(ncol(Hgem$S))
A_sparse <- rbind(Hgem$S, P_sparse)

q <- rep(0, ncol(Hgem$S))
q[which(Hgem$Obj == 1)] <- -10000

cat("Computing Fluxes (Fully Parallelized & Sparse)...\n")

num_cores <- parallel::detectCores()
use_cores <- min(num_cores - 2, ncol(mras_scores)) 
cl <- makeCluster(use_cores)
registerDoParallel(cl)

# Export the large sparse matrices to the workers ONCE
clusterExport(cl, c("P_sparse", "A_sparse", "q", "Hgem", "medium_to_use"))

# Run the highly optimized sparse OSQP solver concurrently
flux_list <- foreach(i = 1:ncol(mras_scores), .packages = c("osqp", "Matrix")) %dopar% {
    single_mras <- mras_scores[, i]
    
    origlb <- Hgem$LB
    origlb[Hgem$rev == 1] <- -single_mras[Hgem$rev == 1]
    origlb[Hgem$rev == 0] <- 0
    origlb <- origlb[, 1]
    
    origub <- single_mras
    
    origlb[Hgem$Reaction %in% Hgem$Reaction[which(Hgem$pathway == "Exchange/demand reactions")]] <- 0
    origlb[Hgem$Reaction %in% medium_to_use$reaction_name] <- -1
    
    l <- c(rep(0, nrow(Hgem$S)), origlb)
    u <- c(rep(0, nrow(Hgem$S)), origub)
    
    settings <- osqpSettings(max_iter = 1000000L, eps_abs = 1e-04, eps_rel = 1e-04, adaptive_rho_interval = 50, verbose = FALSE)
    
    # Use the pre-computed sparse matrices directly!
    model <- osqp(P_sparse, q, A_sparse, l, u, settings)
    res <- model$Solve()
    
    return(res$x)
}

stopCluster(cl)

flux_results <- do.call(cbind, flux_list)
colnames(flux_results) <- colnames(mras_scores)
rownames(flux_results) <- Hgem$Reaction

cat("Saving results...\n")
write.csv(flux_results, "flux_results_salmon.csv")

print("Successfully calculated fluxes and saved to flux_results_salmon.csv")