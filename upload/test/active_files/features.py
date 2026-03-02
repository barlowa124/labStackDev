from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import numpy as np
from PIL import Image


@dataclass
class FeatureConfig:
    min_object_size_px: int = 30
    contact_distance_px: int = 45
    tile_size_px: int = 16
    max_dim_px: int = 768


def _to_gray(img_rgb: np.ndarray) -> np.ndarray:
    return (0.2989 * img_rgb[:, :, 0] + 0.5870 * img_rgb[:, :, 1] + 0.1140 * img_rgb[:, :, 2]) / 255.0


def _otsu_threshold(gray: np.ndarray) -> float:
    vals = np.clip((gray * 255).astype(np.uint8), 0, 255)
    hist = np.bincount(vals.ravel(), minlength=256).astype(float)
    total = vals.size
    sum_total = np.dot(np.arange(256), hist)

    sum_bg = 0.0
    weight_bg = 0.0
    best_var = -1.0
    best_t = 127

    for t in range(256):
        weight_bg += hist[t]
        if weight_bg == 0:
            continue
        weight_fg = total - weight_bg
        if weight_fg == 0:
            break

        sum_bg += t * hist[t]
        mean_bg = sum_bg / weight_bg
        mean_fg = (sum_total - sum_bg) / weight_fg
        between = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
        if between > best_var:
            best_var = between
            best_t = t

    return best_t / 255.0


def _resize_if_needed(img: Image.Image, max_dim: int) -> Image.Image:
    w, h = img.size
    if max(w, h) <= max_dim:
        return img
    scale = max_dim / float(max(w, h))
    new_size = (int(w * scale), int(h * scale))
    return img.resize(new_size, Image.Resampling.BILINEAR)


def _prepare_mask(gray: np.ndarray) -> np.ndarray:
    thresh = _otsu_threshold(gray)
    mask_dark = gray < thresh
    mask_light = gray > thresh

    d_occ = mask_dark.mean()
    l_occ = mask_light.mean()

    def score(occ):
        return abs(occ - 0.32)

    return mask_dark if score(d_occ) <= score(l_occ) else mask_light


def _tile_component_count(mask: np.ndarray, tile_size: int) -> float:
    h, w = mask.shape
    th = max(1, int(tile_size))
    h2 = h // th
    w2 = w // th
    if h2 == 0 or w2 == 0:
        return 0.0

    cropped = mask[: h2 * th, : w2 * th]
    tiles = cropped.reshape(h2, th, w2, th).mean(axis=(1, 3))
    occupied = tiles > 0.12

    visited = np.zeros_like(occupied, dtype=bool)
    count = 0
    neighbors = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    for y in range(h2):
        for x in range(w2):
            if not occupied[y, x] or visited[y, x]:
                continue
            count += 1
            stack = [(y, x)]
            visited[y, x] = True
            while stack:
                cy, cx = stack.pop()
                for dy, dx in neighbors:
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h2 and 0 <= nx < w2 and occupied[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((ny, nx))
    return float(count)


def _nearest_distances(points: np.ndarray) -> np.ndarray:
    if len(points) <= 1:
        return np.array([])
    dists = []
    for idx, p in enumerate(points):
        others = np.delete(points, idx, axis=0)
        local = np.sqrt(((others - p) ** 2).sum(axis=1))
        dists.append(local.min())
    return np.array(dists)


def extract_features(image_path: Path, cfg: FeatureConfig) -> Dict:
    pil = Image.open(image_path).convert("RGB")
    pil = _resize_if_needed(pil, cfg.max_dim_px)
    img = np.asarray(pil)
    gray = _to_gray(img)

    mask = _prepare_mask(gray)

    confluency = float(mask.mean())
    cell_count_est = _tile_component_count(mask, cfg.tile_size_px)

    ys, xs = np.where(mask)
    if len(xs) > 2:
        x_centered = xs.astype(float) - xs.mean()
        y_centered = ys.astype(float) - ys.mean()
        cov = np.cov(np.vstack([x_centered, y_centered]))
        eigvals = np.sort(np.real(np.linalg.eigvals(cov)))
        shape_ecc = float(min(1.0, max(0.0, 1.0 - (eigvals[0] / eigvals[-1])))) if eigvals[-1] > 1e-12 else 0.0
    else:
        shape_ecc = 0.0

    mask_u8 = (mask * 255).astype(np.uint8)
    gx = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
    gy = np.abs(np.diff(gray, axis=0, prepend=gray[:1, :]))
    edge_map = gx + gy
    edge_density = float((edge_map > np.percentile(edge_map, 90)).mean()) if edge_map.size else 0.0

    rgb = img.astype(np.float32) / 255.0
    r = float(rgb[:, :, 0].mean())
    g = float(rgb[:, :, 1].mean())
    b = float(rgb[:, :, 2].mean())
    eps = 1e-8
    r_g_ratio = r / (g + eps)
    g_b_ratio = g / (b + eps)
    r_b_ratio = r / (b + eps)
    rgb_sum = r + g + b + eps
    r_norm = r / rgb_sum
    g_norm = g / rgb_sum
    b_norm = b / rgb_sum

    max_rgb = np.max(rgb, axis=2)
    min_rgb = np.min(rgb, axis=2)
    delta_rgb = max_rgb - min_rgb
    mean_saturation = float((delta_rgb / (max_rgb + eps)).mean())

    hue = np.zeros_like(max_rgb)
    mask = delta_rgb > eps
    r_c = rgb[:, :, 0]
    g_c = rgb[:, :, 1]
    b_c = rgb[:, :, 2]
    idx = (max_rgb == r_c) & mask
    hue[idx] = ((g_c[idx] - b_c[idx]) / (delta_rgb[idx] + eps)) % 6
    idx = (max_rgb == g_c) & mask
    hue[idx] = ((b_c[idx] - r_c[idx]) / (delta_rgb[idx] + eps)) + 2
    idx = (max_rgb == b_c) & mask
    hue[idx] = ((r_c[idx] - g_c[idx]) / (delta_rgb[idx] + eps)) + 4
    hue = (hue / 6.0) % 1.0
    mean_hue = float(hue.mean())

    lap = (
        -4 * gray
        + np.roll(gray, 1, axis=0)
        + np.roll(gray, -1, axis=0)
        + np.roll(gray, 1, axis=1)
        + np.roll(gray, -1, axis=1)
    )
    focus_variance = float(np.var(lap))

    # proxy values for per-cell properties using mask-level descriptors
    mean_area_px = float(mask_u8.sum() / 255.0 / max(1.0, cell_count_est))
    median_area_px = mean_area_px
    mean_solidity = float(1.0 - min(0.95, edge_density * 1.8))
    close_contact_fraction = float(min(1.0, confluency * 1.35))

    features = {
        "image_path": str(image_path),
        "image_width": int(img.shape[1]),
        "image_height": int(img.shape[0]),
        "cell_count_estimate": int(round(cell_count_est)),
        "confluency_fraction": round(confluency, 6),
        "mean_cell_area_px": round(mean_area_px, 4),
        "median_cell_area_px": round(median_area_px, 4),
        "mean_eccentricity": round(shape_ecc, 6),
        "mean_solidity": round(mean_solidity, 6),
        "close_contact_fraction": round(close_contact_fraction, 6),
        "edge_density": round(edge_density, 6),
        "focus_variance": round(focus_variance, 6),
        "channel_mean_r": round(r, 6),
        "channel_mean_g": round(g, 6),
        "channel_mean_b": round(b, 6),
        "r_g_ratio": round(float(r_g_ratio), 6),
        "g_b_ratio": round(float(g_b_ratio), 6),
        "r_b_ratio": round(float(r_b_ratio), 6),
        "r_norm": round(float(r_norm), 6),
        "g_norm": round(float(g_norm), 6),
        "b_norm": round(float(b_norm), 6),
        "mean_hue": round(mean_hue, 6),
        "mean_saturation": round(mean_saturation, 6),
    }
    return features


def summarize_features_text(feat: Dict) -> str:
    confluency = feat.get("confluency_fraction", 0.0)
    ctext = "low" if confluency < 0.25 else "moderate" if confluency < 0.6 else "high"

    ecc = feat.get("mean_eccentricity", 0.0)
    mtext = "rounded" if ecc < 0.45 else "mixed" if ecc < 0.75 else "elongated/spindle-like"

    contact = feat.get("close_contact_fraction", 0.0)
    ttext = "sparse" if contact < 0.2 else "moderate" if contact < 0.5 else "dense"

    return (
        f"Estimated cell state: confluency is {ctext} ({confluency:.2f}), morphology appears {mtext} "
        f"(mean eccentricity {ecc:.2f}), and cell-cell contact is {ttext} "
        f"(close-contact fraction {contact:.2f}). Estimated cell count: {feat.get('cell_count_estimate', 0)}."
    )


def extract_density_products(image_path: Path, grid_size: int = 24, max_dim_px: int = 768) -> Dict:
    pil = Image.open(image_path).convert("RGB")
    pil = _resize_if_needed(pil, max_dim_px)
    img = np.asarray(pil)
    gray = _to_gray(img)
    mask = _prepare_mask(gray)

    grid = max(4, int(grid_size))
    h, w = mask.shape
    ys = np.array_split(np.arange(h), grid)
    xs = np.array_split(np.arange(w), grid)

    heatmap = np.zeros((grid, grid), dtype=np.float32)
    for iy, y_idx in enumerate(ys):
        for ix, x_idx in enumerate(xs):
            tile = mask[np.ix_(y_idx, x_idx)]
            heatmap[iy, ix] = float(tile.mean()) if tile.size else 0.0

    wavetable_x = heatmap.mean(axis=0)
    wavetable_y = heatmap.mean(axis=1)

    media_mask = ~mask
    media_fraction = float(media_mask.mean())
    media_intensity_mean = float(gray[media_mask].mean()) if media_mask.any() else 0.0
    media_texture_variance = float(np.var(gray[media_mask])) if media_mask.any() else 0.0

    return {
        "grid_size": grid,
        "density_heatmap": heatmap,
        "wavetable_x": wavetable_x,
        "wavetable_y": wavetable_y,
        "density_mean": float(heatmap.mean()),
        "density_max": float(heatmap.max()),
        "density_std": float(heatmap.std()),
        "media_fraction": media_fraction,
        "media_intensity_mean": media_intensity_mean,
        "media_texture_variance": media_texture_variance,
    }
