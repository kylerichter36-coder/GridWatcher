#!/usr/bin/env python3
"""
Feature extraction, outage event classification, and compact decision-tree
training/export for GridWatcher v0.3.
"""

import os
import re
import time
import json
import zlib
import hmac
import struct
import hashlib
from typing import Dict, List, Tuple, Optional, Any

import numpy as np
import pandas as pd

from features_gen import (
    GW_SCHEMA_VERSION,
    GW_MODEL_MAGIC,
    GW_FEATURE_HASH,
    GW_NUM_FEATURES,
    FEATURE_NAMES,
    FEATURE_DEFAULTS,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
MODELS_DIR = os.path.join(SCRIPT_DIR, "models")
CPP_MODEL_HEADER_PATH = os.path.join(REPO_DIR, "firmware", "grid_model.h")
VERSION_JSON_PATH = os.path.join(REPO_DIR, "version.json")

DEFAULT_MODEL_SIGNING_KEY = os.environ.get(
    "GW_MODEL_SIGNING_KEY", "gridwatcher-v03-ed25519-hmac-model-signing-key-2026"
)

EVENT_PRECURSOR_OUTAGE = "PRECURSOR_OUTAGE"
EVENT_SCHEDULED_MAINTENANCE = "SCHEDULED_MAINTENANCE"
EVENT_INSTANT_FAULT = "INSTANT_FAULT"
EVENT_QUARANTINED_UNPLUG = "QUARANTINED_UNPLUG"
EVENT_RELOCATED = "RELOCATED"


def sanitize_identifier(raw_id: str, fallback: str = "global") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", str(raw_id or ""))
    return cleaned[:64] if cleaned else fallback


def compute_single_window_features(
    timestamps_s: np.ndarray,
    voltages: np.ndarray,
    frequencies: np.ndarray,
    v_baseline: float = 230.0,
    f_cycle_jitter_override: Optional[float] = None,
) -> np.ndarray:
    """
    Compute the 10-feature vector for the newest sample in a rolling window.
    Matches extract_10_features() in firmware/firmware.ino.
    """
    n = len(voltages)
    if n == 0:
        return np.array([FEATURE_DEFAULTS[k] for k in FEATURE_NAMES], dtype=np.float32)

    v_now = float(voltages[-1])
    f_now = float(frequencies[-1])
    t_now = float(timestamps_s[-1])

    v_delta_baseline = v_now - float(v_baseline)

    if f_cycle_jitter_override is not None:
        f_jitter_mhz = float(f_cycle_jitter_override)
    elif n >= 3:
        recent_f = frequencies[-min(n, 5):]
        f_jitter_mhz = float(np.std(recent_f, ddof=0) * 1000.0)
    else:
        f_jitter_mhz = 5.0

    # 10s rate of change: sample closest to (t_now - 10s) within [1s, 15s]
    dv_dt_10s = 0.0
    df_dt_10s = 0.0
    best_idx = -1
    best_diff = 999999.0
    for k in range(n - 2, -1, -1):
        elapsed = t_now - float(timestamps_s[k])
        if elapsed <= 0.0:
            continue
        if elapsed > 15.0:
            break
        diff = abs(elapsed - 10.0)
        if diff < best_diff:
            best_diff = diff
            best_idx = k

    if best_idx != -1:
        dt = max(1.0, t_now - float(timestamps_s[best_idx]))
        dv_dt_10s = (v_now - float(voltages[best_idx])) / dt
        df_dt_10s = (f_now - float(frequencies[best_idx])) / dt

    # 30s rolling std (ddof=0) and linear regression slope
    mask_30s = (t_now - timestamps_s) <= 30.5
    t_win = timestamps_s[mask_30s].astype(np.float64)
    v_win = voltages[mask_30s].astype(np.float64)
    f_win = frequencies[mask_30s].astype(np.float64)

    if len(v_win) >= 2:
        v_std_30s = float(np.std(v_win, ddof=0))
        f_std_30s = float(np.std(f_win, ddof=0))
        t_rel = t_win - t_win[0]
        t_diff = t_rel - np.mean(t_rel)
        den = float(np.sum(t_diff * t_diff))
        if den > 1e-4:
            v_slope_30s = float(np.sum(t_diff * (v_win - np.mean(v_win))) / den)
            f_slope_30s = float(np.sum(t_diff * (f_win - np.mean(f_win))) / den)
        else:
            v_slope_30s = 0.0
            f_slope_30s = 0.0
    else:
        v_std_30s = 0.0
        f_std_30s = 0.0
        v_slope_30s = 0.0
        f_slope_30s = 0.0

    return np.array(
        [
            v_now,
            v_delta_baseline,
            f_now,
            f_jitter_mhz,
            dv_dt_10s,
            df_dt_10s,
            v_std_30s,
            f_std_30s,
            v_slope_30s,
            f_slope_30s,
        ],
        dtype=np.float32,
    )


def compute_10_features_df(df: pd.DataFrame, default_v_baseline: float = 230.0) -> pd.DataFrame:
    df = df.copy()
    if "v_rms" not in df.columns and "voltage" in df.columns:
        df["v_rms"] = df["voltage"].astype(float)
    elif "v_rms" not in df.columns and "voltage_v" in df.columns:
        df["v_rms"] = df["voltage_v"].astype(float)

    if "f_hz" not in df.columns and "frequency" in df.columns:
        df["f_hz"] = df["frequency"].astype(float)
    elif "f_hz" not in df.columns and "frequency_hz" in df.columns:
        df["f_hz"] = df["frequency_hz"].astype(float)

    if "timestamp_s" in df.columns:
        ts_sec = df["timestamp_s"].astype(float).values
    elif "timestamp" in df.columns:
        if np.issubdtype(df["timestamp"].dtype, np.number):
            ts_sec = df["timestamp"].astype(float).values
        else:
            ts_dt = pd.to_datetime(df["timestamp"], errors="coerce")
            ts_sec = (ts_dt - ts_dt.iloc[0]).dt.total_seconds().fillna(0.0).values
    else:
        ts_sec = np.arange(len(df), dtype=float)

    df["timestamp_s"] = ts_sec
    df = df.sort_values("timestamp_s").reset_index(drop=True)
    ts_sec = df["timestamp_s"].values
    v_arr = df["v_rms"].values.astype(float)
    f_arr = df["f_hz"].values.astype(float)

    if "v_baseline" in df.columns:
        v_base_arr = df["v_baseline"].values.astype(float)
    else:
        normal_mask = (v_arr >= 212.0) & (v_arr <= 248.0) & (f_arr >= 49.6) & (f_arr <= 50.4)
        est_base = float(np.median(v_arr[normal_mask])) if np.any(normal_mask) else default_v_baseline
        v_base_arr = np.full(len(df), est_base, dtype=float)

    has_jitter_col = "f_cycle_jitter" in df.columns
    jitter_arr = df["f_cycle_jitter"].values.astype(float) if has_jitter_col else None

    out_rows = np.zeros((len(df), GW_NUM_FEATURES), dtype=np.float32)
    start_idx = 0
    for i in range(len(df)):
        while start_idx < i and (ts_sec[i] - ts_sec[start_idx]) > 35.0:
            start_idx += 1
        if i > 0 and (ts_sec[i] - ts_sec[i - 1]) > 35.0:
            start_idx = i
        j_ovr = float(jitter_arr[i]) if has_jitter_col else None
        out_rows[i] = compute_single_window_features(
            ts_sec[start_idx : i + 1],
            v_arr[start_idx : i + 1],
            f_arr[start_idx : i + 1],
            v_baseline=float(v_base_arr[i]),
            f_cycle_jitter_override=j_ovr,
        )

    for idx, name in enumerate(FEATURE_NAMES):
        df[name] = out_rows[:, idx]

    return df


def compute_unsupervised_layer2a_risk(feat: np.ndarray) -> float:
    """
    Cold-start baseline instability score (0..100%) before a cluster has
    enough local outage events for supervised retraining.
    """
    v_rms, v_delta, f_hz, f_jitter, dv_dt, df_dt, v_std, f_std, v_slope, f_slope = feat

    score = 0.0
    if v_delta < -4.0:
        score += min(35.0, abs(v_delta + 4.0) * 2.2)
    if v_slope < -0.08:
        score += min(25.0, abs(v_slope) * 45.0)
    if abs(f_hz - 50.0) > 0.25:
        score += min(25.0, (abs(f_hz - 50.0) - 0.25) * 35.0)
    if f_slope < -0.005:
        score += min(20.0, abs(f_slope) * 600.0)
    if f_jitter > 35.0:
        score += min(20.0, (f_jitter - 35.0) * 0.25)
    if v_std > 1.8:
        score += min(15.0, (v_std - 1.8) * 4.0)
    if f_std > 0.12:
        score += min(15.0, (f_std - 0.12) * 35.0)

    return float(np.clip(score, 0.0, 100.0))


def classify_outage_event(
    pre_outage_df: pd.DataFrame,
    drop_duration_ms: float = 20.0,
    pre_cell_id: Optional[str] = None,
    post_cell_id: Optional[str] = None,
    pre_v_baseline: Optional[float] = None,
    post_v_baseline: Optional[float] = None,
    scheduled_maintenance_match: bool = False,
    sibling_co_occurrence: bool = False,
) -> Dict[str, Any]:
    """
    Checks the 60s window before power loss to separate trainable precursor
    collapses from manual unplugs, relocations, and scheduled maintenance cuts.
    """
    df_feat = compute_10_features_df(pre_outage_df)
    if len(df_feat) == 0:
        return {
            "event_type": EVENT_QUARANTINED_UNPLUG,
            "train_eligible": False,
            "relocated": False,
            "reason": "Empty pre-outage trace",
        }

    active_df = df_feat[df_feat["v_rms"] > 150.0]
    if len(active_df) == 0:
        active_df = df_feat

    t_max = float(active_df["timestamp_s"].max())
    win_60s = active_df[active_df["timestamp_s"] >= (t_max - 60.0)]

    max_v_std = float(win_60s["v_std_30s"].max())
    max_f_std = float(win_60s["f_std_30s"].max())
    min_v_slope = float(win_60s["v_slope_30s"].min())
    min_f_slope = float(win_60s["f_slope_30s"].min())
    max_v_delta = float(np.abs(win_60s["v_delta_baseline"]).max())
    max_f_jitter = float(win_60s["f_cycle_jitter"].max())
    min_f_hz = float(win_60s["f_hz"].min())

    cell_changed = (
        pre_cell_id is not None
        and post_cell_id is not None
        and str(pre_cell_id).strip() != str(post_cell_id).strip()
    )
    baseline_shifted = (
        pre_v_baseline is not None
        and post_v_baseline is not None
        and abs(float(post_v_baseline) - float(pre_v_baseline)) > 3.5
    )
    relocated = bool(cell_changed or baseline_shifted)

    has_precursor = bool(
        max_v_std >= 0.85
        or max_f_std >= 0.06
        or min_v_slope <= -0.06
        or min_f_slope <= -0.004
        or max_v_delta >= 3.0
        or max_f_jitter >= 25.0
        or min_f_hz <= 49.65
        or drop_duration_ms > 80.0
    )

    metrics = {
        "max_v_std_30s": round(max_v_std, 4),
        "max_f_std_30s": round(max_f_std, 4),
        "min_v_slope_30s": round(min_v_slope, 4),
        "min_f_slope_30s": round(min_f_slope, 5),
        "max_v_delta": round(max_v_delta, 3),
        "max_f_cycle_jitter_mhz": round(max_f_jitter, 2),
        "drop_duration_ms": float(drop_duration_ms),
    }

    if relocated and not has_precursor:
        return {
            "event_type": EVENT_RELOCATED,
            "train_eligible": False,
            "relocated": True,
            "reason": "CellID or resting voltage baseline shifted after disconnect",
            "metrics": metrics,
        }

    if scheduled_maintenance_match and not has_precursor:
        return {
            "event_type": EVENT_SCHEDULED_MAINTENANCE,
            "train_eligible": False,
            "relocated": relocated,
            "reason": "Matched municipal/utility scheduled maintenance window",
            "metrics": metrics,
        }

    if has_precursor:
        return {
            "event_type": EVENT_PRECURSOR_OUTAGE,
            "train_eligible": True,
            "relocated": relocated,
            "reason": "Pre-outage voltage sag / frequency jitter detected prior to drop",
            "metrics": metrics,
        }

    if sibling_co_occurrence:
        return {
            "event_type": EVENT_INSTANT_FAULT,
            "train_eligible": False,
            "relocated": relocated,
            "reason": "Instant fault confirmed by sibling unit losing power at the same time",
            "metrics": metrics,
        }

    return {
        "event_type": EVENT_QUARANTINED_UNPLUG,
        "train_eligible": False,
        "relocated": relocated,
        "reason": "Flat 230V/50Hz line with instant open-circuit drop; quarantined from training",
        "metrics": metrics,
    }


def label_outage_trace(df: pd.DataFrame, outage_start_ts: float, train_eligible: bool = True) -> pd.DataFrame:
    df_feat = compute_10_features_df(df)
    alive_mask = df_feat["v_rms"].values >= 150.0
    df_feat = df_feat[alive_mask].copy()
    t = df_feat["timestamp_s"].values

    if train_eligible:
        in_buffer = (t >= (outage_start_ts - 180.0)) & (t < (outage_start_ts - 60.0))
        df_feat = df_feat[~in_buffer].copy()
        t = df_feat["timestamp_s"].values
        df_feat["target_risk"] = np.where(
            (t >= (outage_start_ts - 60.0)) & (t <= outage_start_ts), 1, 0
        )
    else:
        df_feat = df_feat[t < (outage_start_ts - 180.0)].copy()
        df_feat["target_risk"] = 0

    return df_feat.reset_index(drop=True)


def _build_cart_tree(
    X: np.ndarray,
    y: np.ndarray,
    sample_weights: np.ndarray,
    tree_id: int,
    max_depth: int,
    min_samples_leaf: int,
    rng: np.random.Generator,
    extra_trees: bool = False,
) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    n_features = X.shape[1]
    k_features = max(3, int(np.sqrt(n_features)) + 1)

    def _recurse(indices: np.ndarray, depth: int) -> int:
        node_idx = len(nodes)
        nodes.append(
            {
                "feature_idx": -1,
                "tree_id": tree_id,
                "left_child": -1,
                "right_child": -1,
                "threshold_or_prob": 0.0,
            }
        )

        y_sub = y[indices]
        w_sub = sample_weights[indices]
        w_total = float(np.sum(w_sub))
        w_pos = float(np.sum(w_sub[y_sub == 1]))
        prob_pos = (w_pos / w_total) if w_total > 0.0 else 0.0

        if (
            depth >= max_depth
            or len(indices) < 2 * min_samples_leaf
            or prob_pos <= 1e-5
            or prob_pos >= (1.0 - 1e-5)
        ):
            nodes[node_idx]["threshold_or_prob"] = round(prob_pos, 6)
            return node_idx

        parent_gini = 2.0 * prob_pos * (1.0 - prob_pos)
        feat_candidates = rng.choice(n_features, size=min(n_features, k_features), replace=False)

        best_gain = 1e-6
        best_feat = -1
        best_thresh = 0.0
        best_left_mask = None

        for f_idx in feat_candidates:
            col = X[indices, f_idx]
            c_min, c_max = float(np.min(col)), float(np.max(col))
            if (c_max - c_min) < 1e-6:
                continue

            if extra_trees:
                thresholds = rng.uniform(c_min, c_max, size=6)
            else:
                thresholds = np.quantile(col, [0.15, 0.30, 0.45, 0.55, 0.70, 0.85])

            for thresh in np.unique(thresholds):
                left_mask = col <= thresh
                n_left = int(np.sum(left_mask))
                n_right = len(indices) - n_left
                if n_left < min_samples_leaf or n_right < min_samples_leaf:
                    continue

                w_left = float(np.sum(w_sub[left_mask]))
                w_right = w_total - w_left
                if w_left <= 0.0 or w_right <= 0.0:
                    continue

                p_left = float(np.sum(w_sub[left_mask & (y_sub == 1)])) / w_left
                p_right = (w_pos - float(np.sum(w_sub[left_mask & (y_sub == 1)]))) / w_right

                gini_left = 2.0 * p_left * (1.0 - p_left)
                gini_right = 2.0 * p_right * (1.0 - p_right)
                weighted_child_gini = (w_left / w_total) * gini_left + (w_right / w_total) * gini_right
                gain = parent_gini - weighted_child_gini

                if gain > best_gain:
                    best_gain = gain
                    best_feat = int(f_idx)
                    best_thresh = float(thresh)
                    best_left_mask = left_mask

        if best_feat < 0 or best_left_mask is None:
            nodes[node_idx]["threshold_or_prob"] = round(prob_pos, 6)
            return node_idx

        left_indices = indices[best_left_mask]
        right_indices = indices[~best_left_mask]

        left_child_idx = _recurse(left_indices, depth + 1)
        right_child_idx = _recurse(right_indices, depth + 1)

        nodes[node_idx]["feature_idx"] = best_feat
        nodes[node_idx]["left_child"] = left_child_idx
        nodes[node_idx]["right_child"] = right_child_idx
        nodes[node_idx]["threshold_or_prob"] = round(best_thresh, 6)
        return node_idx

    _recurse(np.arange(len(y)), 0)
    return nodes


def train_numpy_forest(
    X: np.ndarray,
    y: np.ndarray,
    n_estimators: int = 11,
    max_depth: int = 4,
    min_samples_leaf: int = 4,
    extra_trees: bool = False,
    seed: int = 42,
) -> Tuple[List[Dict[str, Any]], List[int]]:
    rng = np.random.default_rng(seed)
    n_samples = len(y)
    n_pos = max(1, int(np.sum(y == 1)))
    n_neg = max(1, int(np.sum(y == 0)))

    w_pos = n_samples / (2.0 * n_pos)
    w_neg = n_samples / (2.0 * n_neg)
    base_weights = np.where(y == 1, w_pos, w_neg).astype(np.float64)

    flat_nodes: List[Dict[str, Any]] = []
    tree_roots: List[int] = []

    for tree_id in range(n_estimators):
        boot_idx = rng.integers(0, n_samples, size=n_samples)
        local_nodes = _build_cart_tree(
            X[boot_idx],
            y[boot_idx],
            base_weights[boot_idx],
            tree_id=tree_id,
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            rng=rng,
            extra_trees=extra_trees,
        )
        root_offset = len(flat_nodes)
        tree_roots.append(root_offset)
        for nd in local_nodes:
            flat_nodes.append(
                {
                    "feature_idx": nd["feature_idx"],
                    "tree_id": tree_id,
                    "left_child": (root_offset + nd["left_child"]) if nd["left_child"] >= 0 else -1,
                    "right_child": (root_offset + nd["right_child"]) if nd["right_child"] >= 0 else -1,
                    "threshold_or_prob": nd["threshold_or_prob"],
                }
            )

    return flat_nodes, tree_roots


def evaluate_flat_model_single(
    feat_vec: np.ndarray,
    flat_nodes: List[Dict[str, Any]],
    tree_roots: List[int],
) -> Tuple[float, List[float]]:
    if not tree_roots or not flat_nodes:
        return compute_unsupervised_layer2a_risk(feat_vec), []

    tree_probs: List[float] = []
    for root_idx in tree_roots:
        curr = root_idx
        steps = 0
        while 0 <= curr < len(flat_nodes) and steps < 64:
            node = flat_nodes[curr]
            f_idx = node["feature_idx"]
            if f_idx < 0:
                tree_probs.append(float(node["threshold_or_prob"]) * 100.0)
                break
            if float(feat_vec[f_idx]) <= float(node["threshold_or_prob"]):
                curr = node["left_child"]
            else:
                curr = node["right_child"]
            steps += 1
        else:
            tree_probs.append(0.0)

    avg_risk = float(np.mean(tree_probs)) if tree_probs else 0.0
    return avg_risk, tree_probs


def evaluate_flat_model_batch(
    X: np.ndarray,
    flat_nodes: List[Dict[str, Any]],
    tree_roots: List[int],
    ema_alpha: float = 0.4,
) -> Tuple[np.ndarray, np.ndarray]:
    n = len(X)
    raw_scores = np.zeros(n, dtype=np.float32)
    ema_scores = np.zeros(n, dtype=np.float32)
    for i in range(n):
        r, _ = evaluate_flat_model_single(X[i], flat_nodes, tree_roots)
        raw_scores[i] = r
        if i == 0:
            ema_scores[i] = r
        else:
            ema_scores[i] = ema_alpha * r + (1.0 - ema_alpha) * ema_scores[i - 1]
    return raw_scores, ema_scores


def pack_signed_binary_model(
    flat_nodes: List[Dict[str, Any]],
    tree_roots: List[int],
    model_version: int,
    signing_key: str = DEFAULT_MODEL_SIGNING_KEY,
) -> bytes:
    """
    Pack flat decision trees into a signed binary payload (<5KB) for ESP32-S3 OTA reload.
    """
    roots_bytes = struct.pack(f"<{len(tree_roots)}H", *tree_roots)
    node_chunks = []
    for n in flat_nodes:
        node_chunks.append(
            struct.pack(
                "<bBhhf",
                int(n["feature_idx"]),
                int(n["tree_id"]),
                int(n["left_child"]),
                int(n["right_child"]),
                float(n["threshold_or_prob"]),
            )
        )
    nodes_bytes = b"".join(node_chunks)
    nodes_crc32 = zlib.crc32(roots_bytes + nodes_bytes) & 0xFFFFFFFF

    header_prefix = struct.pack(
        "<IHHHHIII",
        GW_MODEL_MAGIC,
        GW_SCHEMA_VERSION,
        len(tree_roots),
        len(flat_nodes),
        0,
        GW_FEATURE_HASH,
        int(model_version),
        nodes_crc32,
    )
    mac = hmac.new(
        signing_key.encode("utf-8"),
        header_prefix + roots_bytes + nodes_bytes,
        hashlib.sha256,
    ).digest()

    return header_prefix + mac + roots_bytes + nodes_bytes


def verify_and_unpack_binary_model(
    payload: bytes,
    signing_key: str = DEFAULT_MODEL_SIGNING_KEY,
) -> Dict[str, Any]:
    if len(payload) < 56:
        raise ValueError("Binary model payload too short (<56 bytes)")

    magic, schema_ver, n_trees, n_nodes, _, feat_hash, model_ver, crc32_expected = struct.unpack(
        "<IHHHHIII", payload[:24]
    )
    sig_received = payload[24:56]
    if magic != GW_MODEL_MAGIC:
        raise ValueError(f"Invalid model magic: 0x{magic:08X}")
    if schema_ver != GW_SCHEMA_VERSION:
        raise ValueError(f"Schema version mismatch: {schema_ver} != {GW_SCHEMA_VERSION}")
    if feat_hash != GW_FEATURE_HASH:
        raise ValueError(f"Feature hash mismatch: 0x{feat_hash:08X} != 0x{GW_FEATURE_HASH:08X}")

    body = payload[56:]
    expected_mac = hmac.new(
        signing_key.encode("utf-8"),
        payload[:24] + body,
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(sig_received, expected_mac):
        raise ValueError("Model HMAC-SHA256 signature verification failed")

    actual_crc = zlib.crc32(body) & 0xFFFFFFFF
    if actual_crc != crc32_expected:
        raise ValueError(f"Model CRC32 mismatch: 0x{actual_crc:08X} != 0x{crc32_expected:08X}")

    roots_len = n_trees * 2
    if len(body) < roots_len + n_nodes * 10:
        raise ValueError("Truncated binary model node table")

    tree_roots = list(struct.unpack(f"<{n_trees}H", body[:roots_len]))
    nodes_buf = body[roots_len:]
    flat_nodes = []
    for i in range(n_nodes):
        offset = i * 10
        f_idx, t_id, left, right, val = struct.unpack("<bBhhf", nodes_buf[offset : offset + 10])
        flat_nodes.append(
            {
                "feature_idx": f_idx,
                "tree_id": t_id,
                "left_child": left,
                "right_child": right,
                "threshold_or_prob": float(val),
            }
        )

    return {
        "model_version": model_ver,
        "schema_version": schema_ver,
        "feature_hash": f"0x{feat_hash:08X}",
        "n_trees": n_trees,
        "n_nodes": n_nodes,
        "tree_roots": tree_roots,
        "flat_nodes": flat_nodes,
        "crc32": f"0x{crc32_expected:08X}",
    }


def _compute_pr_auc(y_true: np.ndarray, probs: np.ndarray) -> float:
    if np.sum(y_true) == 0 or np.sum(y_true) == len(y_true):
        return 1.0 if np.sum(y_true) > 0 else 0.0
    thresholds = np.linspace(0.0, 1.0, 101)
    precisions = []
    recalls = []
    pos_total = float(np.sum(y_true == 1))
    for th in thresholds:
        pred = probs >= th
        tp = float(np.sum(pred & (y_true == 1)))
        fp = float(np.sum(pred & (y_true == 0)))
        prec = (tp / (tp + fp)) if (tp + fp) > 0 else 1.0
        rec = tp / pos_total
        precisions.append(prec)
        recalls.append(rec)
    recalls_arr = np.array(recalls)[::-1]
    precisions_arr = np.array(precisions)[::-1]
    return float(
        np.trapezoid(precisions_arr, recalls_arr)
        if hasattr(np, "trapezoid")
        else np.trapz(precisions_arr, recalls_arr)
    )


def evaluate_outage_metrics(
    df_eval: pd.DataFrame,
    ema_risk_scores: np.ndarray,
    alert_threshold: float = 65.0,
) -> Dict[str, float]:
    y_true = df_eval["target_risk"].values.astype(int)
    t_sec = df_eval["timestamp_s"].values.astype(float)
    y_pred = (ema_risk_scores >= alert_threshold).astype(int)

    pr_auc_val = _compute_pr_auc(y_true, ema_risk_scores / 100.0)
    tp = float(np.sum((y_pred == 1) & (y_true == 1)))
    fp = float(np.sum((y_pred == 1) & (y_true == 0)))
    fn = float(np.sum((y_pred == 0) & (y_true == 1)))
    f1_val = (2.0 * tp / (2.0 * tp + fp + fn)) if (2.0 * tp + fp + fn) > 0 else 0.0

    episodes: List[Tuple[int, int]] = []
    in_ep = False
    ep_start = 0
    for i, val in enumerate(y_true):
        if val == 1 and not in_ep:
            in_ep = True
            ep_start = i
        elif val == 0 and in_ep:
            in_ep = False
            episodes.append((ep_start, i - 1))
    if in_ep:
        episodes.append((ep_start, len(y_true) - 1))

    detected_20s = 0
    lead_times: List[float] = []
    for start_i, end_i in episodes:
        t_collapse = t_sec[end_i]
        alert_indices = [
            idx for idx in range(start_i, end_i + 1) if ema_risk_scores[idx] >= alert_threshold
        ]
        if alert_indices:
            first_alert_t = t_sec[alert_indices[0]]
            lead_s = max(0.0, t_collapse - first_alert_t)
            lead_times.append(lead_s)
            if lead_s >= 20.0:
                detected_20s += 1
        else:
            lead_times.append(0.0)

    event_recall_20s = (detected_20s / len(episodes) * 100.0) if episodes else 100.0
    mean_lead_time_s = float(np.mean(lead_times)) if lead_times else 35.0

    false_alarm_count = 0
    last_fa_time = -999999.0
    for i in range(len(y_true)):
        if y_true[i] == 0 and y_pred[i] == 1:
            if (t_sec[i] - last_fa_time) >= 600.0:
                false_alarm_count += 1
                last_fa_time = t_sec[i]

    total_duration_days = max(1e-3, (t_sec[-1] - t_sec[0]) / 86400.0) if len(t_sec) > 1 else (1.0 / 24.0)
    false_alarms_per_day = float(false_alarm_count / total_duration_days)

    return {
        "event_recall_at_20s_pct": round(event_recall_20s, 2),
        "mean_lead_time_s": round(mean_lead_time_s, 1),
        "false_alarms_per_day": round(false_alarms_per_day, 3),
        "pr_auc": round(pr_auc_val, 4),
        "f1_score": round(f1_val, 4),
        "episodes_evaluated": len(episodes),
    }


def generate_realistic_sa_dataset(seed: int = 42) -> pd.DataFrame:
    """
    Synthetic South African grid trace with normal noise, hard-negative household
    appliance sags (kettle/geyser switching), and precursor feeder collapses.
    """
    rng = np.random.default_rng(seed)
    dt_step = 2.0
    n_samples = 1800
    timestamps_s = np.arange(n_samples, dtype=float) * dt_step

    v_base = 230.0
    v_rms = v_base + rng.normal(0.0, 0.35, n_samples)
    f_hz = 50.0 + rng.normal(0.0, 0.018, n_samples)
    f_jitter = np.clip(rng.normal(6.0, 2.0, n_samples), 1.5, 22.0)
    target_risk = np.zeros(n_samples, dtype=int)

    # Hard-negative load step drops (voltage sags 4-6V, frequency & ZX jitter stay steady)
    hard_neg_starts = [150, 550, 980, 1420]
    for hs in hard_neg_starts:
        dur = 35
        sag_v = rng.uniform(3.8, 6.2)
        v_rms[hs : hs + dur] -= sag_v + rng.normal(0.0, 0.25, dur)
        f_hz[hs : hs + dur] += rng.normal(0.0, 0.015, dur)
        f_jitter[hs : hs + dur] = np.clip(rng.normal(8.0, 2.5, dur), 2.0, 18.0)

    # Precursor grid collapse events (60s progressive voltage slope + under-frequency jitter)
    outage_starts = [320, 760, 1200, 1620]
    for os_idx in outage_starts:
        win_len = 30
        progress = np.linspace(0.15, 1.0, win_len)
        sag_curve = (progress ** 1.25) * rng.uniform(12.0, 24.0)
        turbulence = rng.normal(0.0, 1.5 + 2.0 * progress, win_len)
        v_rms[os_idx : os_idx + win_len] = (v_base - sag_curve) + turbulence

        freq_drop = (progress ** 1.15) * rng.uniform(0.42, 0.95)
        f_hz[os_idx : os_idx + win_len] = 50.0 - freq_drop + rng.normal(0.0, 0.08 * (1 + progress), win_len)
        f_jitter[os_idx : os_idx + win_len] = np.linspace(38.0, rng.uniform(95.0, 180.0), win_len) + rng.normal(0, 5.0, win_len)
        target_risk[os_idx : os_idx + win_len] = 1

    df = pd.DataFrame(
        {
            "timestamp_s": timestamps_s,
            "v_rms": np.round(v_rms, 3),
            "f_hz": np.round(f_hz, 4),
            "f_cycle_jitter": np.round(np.clip(f_jitter, 1.0, 500.0), 2),
            "v_baseline": np.full(n_samples, v_base),
            "target_risk": target_risk,
        }
    )
    return compute_10_features_df(df, default_v_baseline=v_base)


def export_cpp_model_header(
    flat_nodes: List[Dict[str, Any]],
    tree_roots: List[int],
    model_version: int,
    metrics: Dict[str, Any],
    out_path: str = CPP_MODEL_HEADER_PATH,
) -> None:
    build_time = time.strftime("%Y-%m-%d %H:%M:%S")
    roots_str = ", ".join(str(r) for r in tree_roots)
    node_lines = []
    for idx, n in enumerate(flat_nodes):
        node_lines.append(
            f"    {{ {n['feature_idx']:2d}, {n['tree_id']:2d}U, {n['left_child']:4d}, {n['right_child']:4d}, {n['threshold_or_prob']:.6f}f }} /* [{idx}] */"
        )
    nodes_block = ",\n".join(node_lines)

    metrics_summary = (
        f"Recall@20s: {metrics.get('event_recall_at_20s_pct', 0):.1f}% | "
        f"FA/day: {metrics.get('false_alarms_per_day', 0):.2f} | "
        f"PR-AUC: {metrics.get('pr_auc', 0):.3f}"
    )

    cpp_code = f"""// Generated on: {build_time}
// Validation Metrics: {metrics_summary}

#ifndef GRID_MODEL_H
#define GRID_MODEL_H

#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <math.h>
#include "features_gen.h"

enum GridStatus : uint8_t {{
    STATUS_NORMAL        = 0,
    STATUS_BROWNOUT_SAG  = 1,
    STATUS_VOLTAGE_SURGE = 2,
    STATUS_FREQ_JITTER   = 3,
    STATUS_BLACKOUT      = 4
}};

#ifndef ML_MODEL_VERSION
#define ML_MODEL_VERSION {model_version}
#endif

#ifndef ML_MODEL_BUILD_TIME
#define ML_MODEL_BUILD_TIME "{build_time}"
#endif

#ifndef ML_MODEL_METRICS
#define ML_MODEL_METRICS "{metrics_summary}"
#endif

#define GW_MAX_DYNAMIC_TREES  24U
#define GW_MAX_DYNAMIC_NODES  1024U

#pragma pack(push, 1)
struct FlatTreeNode {{
    int8_t   feature_idx;       // 0..9 feature index, or -1 for leaf
    uint8_t  tree_id;
    int16_t  left_child;
    int16_t  right_child;
    float    threshold_or_prob;
}};

struct BinaryModelHeader {{
    uint32_t magic;             // 0x47574D33 ('GWM3')
    uint16_t schema_version;    // 3
    uint16_t n_trees;
    uint16_t n_nodes;
    uint16_t reserved;
    uint32_t feature_hash;      // 0xB7DCECA1
    uint32_t model_version;
    uint32_t nodes_crc32;
    uint8_t  hmac_sha256[32];
}};
#pragma pack(pop)

static const uint16_t DEFAULT_TREE_ROOTS[{len(tree_roots)}] = {{ {roots_str} }};

static const FlatTreeNode DEFAULT_FLAT_NODES[{len(flat_nodes)}] = {{
{nodes_block}
}};

struct DynamicEnsembleModel {{
    bool         has_custom_model;
    uint32_t     active_version;
    uint16_t     n_trees;
    uint16_t     n_nodes;
    uint16_t     tree_roots[GW_MAX_DYNAMIC_TREES];
    FlatTreeNode nodes[GW_MAX_DYNAMIC_NODES];
}};

inline float evaluateLayer2AUnsupervised(const float feat[GW_NUM_FEATURES]) {{
    const float v_delta  = feat[FEAT_V_DELTA_BASELINE];
    const float f_hz     = feat[FEAT_F_HZ];
    const float f_jitter = feat[FEAT_F_CYCLE_JITTER];
    const float v_std    = feat[FEAT_V_STD_30S];
    const float f_std    = feat[FEAT_F_STD_30S];
    const float v_slope  = feat[FEAT_V_SLOPE_30S];
    const float f_slope  = feat[FEAT_F_SLOPE_30S];

    float score = 0.0f;
    if (v_delta < -4.0f) {{
        float s = fabsf(v_delta + 4.0f) * 2.2f;
        score += (s < 35.0f) ? s : 35.0f;
    }}
    if (v_slope < -0.08f) {{
        float s = fabsf(v_slope) * 45.0f;
        score += (s < 25.0f) ? s : 25.0f;
    }}
    if (fabsf(f_hz - 50.0f) > 0.25f) {{
        float s = (fabsf(f_hz - 50.0f) - 0.25f) * 35.0f;
        score += (s < 25.0f) ? s : 25.0f;
    }}
    if (f_slope < -0.005f) {{
        float s = fabsf(f_slope) * 600.0f;
        score += (s < 20.0f) ? s : 20.0f;
    }}
    if (f_jitter > 35.0f) {{
        float s = (f_jitter - 35.0f) * 0.25f;
        score += (s < 20.0f) ? s : 20.0f;
    }}
    if (v_std > 1.8f) {{
        float s = (v_std - 1.8f) * 4.0f;
        score += (s < 15.0f) ? s : 15.0f;
    }}
    if (f_std > 0.12f) {{
        float s = (f_std - 0.12f) * 35.0f;
        score += (s < 15.0f) ? s : 15.0f;
    }}
    return (score > 100.0f) ? 100.0f : score;
}}

inline float evaluateFlatNodeArray(
    const float feat[GW_NUM_FEATURES],
    const FlatTreeNode* nodes,
    uint16_t n_nodes,
    const uint16_t* roots,
    uint16_t n_trees
) {{
    if (!nodes || !roots || n_trees == 0 || n_nodes == 0) {{
        return evaluateLayer2AUnsupervised(feat);
    }}
    float prob_sum = 0.0f;
    for (uint16_t t = 0; t < n_trees; ++t) {{
        int16_t curr = (int16_t)roots[t];
        uint8_t depth_guard = 0;
        while (curr >= 0 && (uint16_t)curr < n_nodes && depth_guard < 32) {{
            const FlatTreeNode& nd = nodes[curr];
            if (nd.feature_idx < 0) {{
                prob_sum += nd.threshold_or_prob;
                break;
            }}
            if ((uint8_t)nd.feature_idx < GW_NUM_FEATURES && feat[nd.feature_idx] <= nd.threshold_or_prob) {{
                curr = nd.left_child;
            }} else {{
                curr = nd.right_child;
            }}
            ++depth_guard;
        }}
    }}
    return (prob_sum / (float)n_trees) * 100.0f;
}}

inline float predictGridRisk(
    const float feat[GW_NUM_FEATURES],
    const DynamicEnsembleModel* dyn_model = nullptr
) {{
    if (dyn_model && dyn_model->has_custom_model && dyn_model->n_trees > 0) {{
        return evaluateFlatNodeArray(
            feat,
            dyn_model->nodes,
            dyn_model->n_nodes,
            dyn_model->tree_roots,
            dyn_model->n_trees
        );
    }}
    return evaluateFlatNodeArray(
        feat,
        DEFAULT_FLAT_NODES,
        (uint16_t)(sizeof(DEFAULT_FLAT_NODES) / sizeof(DEFAULT_FLAT_NODES[0])),
        DEFAULT_TREE_ROOTS,
        (uint16_t)(sizeof(DEFAULT_TREE_ROOTS) / sizeof(DEFAULT_TREE_ROOTS[0]))
    );
}}

inline uint32_t gwCrc32Ieee(const uint8_t* data, size_t len) {{
    uint32_t crc = 0xFFFFFFFFUL;
    for (size_t i = 0; i < len; ++i) {{
        crc ^= (uint32_t)data[i];
        for (uint8_t b = 0; b < 8; ++b) {{
            if (crc & 1UL) {{
                crc = (crc >> 1) ^ 0xEDB88320UL;
            }} else {{
                crc >>= 1;
            }}
        }}
    }}
    return ~crc;
}}

inline bool loadDynamicBinaryModel(
    const uint8_t* payload,
    size_t len,
    DynamicEnsembleModel* out_model
) {{
    if (!payload || !out_model || len < sizeof(BinaryModelHeader)) {{
        return false;
    }}
    BinaryModelHeader hdr;
    memcpy(&hdr, payload, sizeof(BinaryModelHeader));
    if (hdr.magic != 0x47574D33UL) {{
        return false;
    }}
    if (hdr.schema_version != GW_SCHEMA_VERSION || hdr.feature_hash != GW_FEATURE_HASH) {{
        return false;
    }}
    if (hdr.n_trees == 0 || hdr.n_trees > GW_MAX_DYNAMIC_TREES ||
        hdr.n_nodes == 0 || hdr.n_nodes > GW_MAX_DYNAMIC_NODES) {{
        return false;
    }}
    const size_t roots_bytes = (size_t)hdr.n_trees * sizeof(uint16_t);
    const size_t nodes_bytes = (size_t)hdr.n_nodes * sizeof(FlatTreeNode);
    const size_t body_len = roots_bytes + nodes_bytes;
    if (len < sizeof(BinaryModelHeader) + body_len) {{
        return false;
    }}
    const uint8_t* body = payload + sizeof(BinaryModelHeader);
    if (gwCrc32Ieee(body, body_len) != hdr.nodes_crc32) {{
        return false;
    }}
    memcpy(out_model->tree_roots, body, roots_bytes);
    memcpy(out_model->nodes, body + roots_bytes, nodes_bytes);
    out_model->n_trees = hdr.n_trees;
    out_model->n_nodes = hdr.n_nodes;
    out_model->active_version = hdr.model_version;
    out_model->has_custom_model = true;
    return true;
}}

#endif // GRID_MODEL_H
"""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(cpp_code)


def train_regional_model(
    df_train_raw: Optional[pd.DataFrame] = None,
    cluster_id: str = "global",
    model_version: Optional[int] = None,
    update_cpp_header: bool = True,
) -> Dict[str, Any]:
    cluster_id = sanitize_identifier(cluster_id, "global")

    if df_train_raw is None or len(df_train_raw) < 100:
        df = generate_realistic_sa_dataset(seed=42)
    else:
        df = compute_10_features_df(df_train_raw)
        if "target_risk" not in df.columns:
            raise ValueError("Training DataFrame must contain 'target_risk' column")

    X = df[FEATURE_NAMES].values.astype(np.float32)
    y = df["target_risk"].values.astype(int)

    split_idx = int(len(df) * 0.75)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]
    df_test = df.iloc[split_idx:].reset_index(drop=True)

    candidates = [
        ("RandomForest", 9, 4, False),
        ("RandomForest", 11, 4, False),
        ("RandomForest", 13, 5, False),
        ("ExtraTrees", 11, 4, True),
    ]

    best_score = -1e9
    best_bundle = None

    for idx_c, (kind, n_trees, max_depth, is_et) in enumerate(candidates):
        flat_nodes, tree_roots = train_numpy_forest(
            X_train,
            y_train,
            n_estimators=n_trees,
            max_depth=max_depth,
            min_samples_leaf=4,
            extra_trees=is_et,
            seed=42 + idx_c,
        )
        _, ema_test = evaluate_flat_model_batch(X_test, flat_nodes, tree_roots)
        metrics = evaluate_outage_metrics(df_test, ema_test, alert_threshold=65.0)

        fitness = (
            metrics["event_recall_at_20s_pct"] * 1.0
            + metrics["pr_auc"] * 100.0
            - metrics["false_alarms_per_day"] * 25.0
            - len(flat_nodes) * 0.01
        )
        if fitness > best_score:
            best_score = fitness
            best_bundle = (kind, n_trees, max_depth, flat_nodes, tree_roots, metrics)

    kind, n_trees, max_depth, flat_nodes, tree_roots, metrics = best_bundle

    if model_version is None:
        if os.path.exists(VERSION_JSON_PATH):
            try:
                with open(VERSION_JSON_PATH, "r", encoding="utf-8") as vf:
                    model_version = int(json.load(vf).get("version", 40)) + 1
            except Exception:
                model_version = 41
        else:
            model_version = 41

    os.makedirs(MODELS_DIR, exist_ok=True)
    bin_payload = pack_signed_binary_model(flat_nodes, tree_roots, model_version)
    bin_path = os.path.join(MODELS_DIR, f"cluster_{cluster_id}.bin")
    with open(bin_path, "wb") as bf:
        bf.write(bin_payload)

    build_time = time.strftime("%Y-%m-%d %H:%M:%S")
    json_meta = {
        "cluster_id": cluster_id,
        "model_version": model_version,
        "schema_version": GW_SCHEMA_VERSION,
        "feature_hash": f"0x{GW_FEATURE_HASH:08X}",
        "feature_names": FEATURE_NAMES,
        "model_type": kind,
        "n_trees": len(tree_roots),
        "max_depth": max_depth,
        "n_nodes": len(flat_nodes),
        "binary_size_bytes": len(bin_payload),
        "build_time": build_time,
        "metrics": metrics,
        "tree_roots": tree_roots,
        "flat_nodes": flat_nodes,
    }
    json_path = os.path.join(MODELS_DIR, f"cluster_{cluster_id}.json")
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(json_meta, jf, indent=2)

    if update_cpp_header:
        export_cpp_model_header(flat_nodes, tree_roots, model_version, metrics)
        with open(VERSION_JSON_PATH, "w", encoding="utf-8") as vf:
            json.dump(
                {
                    "version": model_version,
                    "schema_version": GW_SCHEMA_VERSION,
                    "feature_hash": f"0x{GW_FEATURE_HASH:08X}",
                    "build_time": build_time,
                    "metrics": metrics,
                },
                vf,
                indent=2,
            )

    return json_meta


def fetch_telemetry_csv(
    telemetry_url: str = "http://127.0.0.1:8000/api/telemetry.csv",
    local_csv_path: Optional[str] = None,
    timeout: float = 1.5,
) -> Dict[str, Any]:
    """
    Fetch telemetry CSV over HTTP (`telemetry_url`), saving to `local_csv_path`.
    Falls back to existing local `telemetry.csv` or root `gridwatcher_dataset.csv`.
    """
    import urllib.request

    if local_csv_path is None:
        local_csv_path = os.path.join(SCRIPT_DIR, "telemetry.csv")
    root_dataset_path = os.path.join(REPO_DIR, "gridwatcher_dataset.csv")

    try:
        req = urllib.request.Request(telemetry_url, headers={"Accept": "text/csv"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_bytes = resp.read()
        if raw_bytes and b"," in raw_bytes:
            os.makedirs(os.path.dirname(local_csv_path), exist_ok=True)
            with open(local_csv_path, "wb") as f:
                f.write(raw_bytes)
            n_rows = max(0, raw_bytes.count(b"\n") - 1)
            return {
                "ok": True,
                "source": "remote_http",
                "url": telemetry_url,
                "path": local_csv_path,
                "rows": n_rows,
                "error": "",
            }
    except Exception as err:
        http_err = str(err)
    else:
        http_err = "Empty CSV response"

    for candidate_path, tag in ((local_csv_path, "local_csv"), (root_dataset_path, "root_dataset")):
        if os.path.exists(candidate_path) and os.path.getsize(candidate_path) > 32:
            with open(candidate_path, "rb") as f:
                # Count lines up to 5000 for speed on large files
                sample = f.read(512 * 1024)
            n_rows = max(1, sample.count(b"\n") - 1)
            return {
                "ok": True,
                "source": tag,
                "url": telemetry_url,
                "path": candidate_path,
                "rows": n_rows,
                "error": http_err,
            }

    return {
        "ok": False,
        "source": "none",
        "url": telemetry_url,
        "path": local_csv_path,
        "rows": 0,
        "error": http_err,
    }


def load_csv_telemetry(
    csv_path: Optional[str] = None,
    max_rows: int = 2500,
) -> pd.DataFrame:
    """
    Load a telemetry CSV file (supporting `telemetry.csv`, `gridwatcher_dataset.csv`,
    and `collected_telemetry.csv` column layouts) and compute the 10 Schema v3 features.
    """
    if csv_path is None:
        cand1 = os.path.join(SCRIPT_DIR, "server_state", "collected_telemetry.csv")
        cand2 = os.path.join(REPO_DIR, "gridwatcher_dataset.csv")
        cand3 = os.path.join(SCRIPT_DIR, "telemetry.csv")
        for c in (cand1, cand2, cand3):
            if os.path.exists(c) and os.path.getsize(c) > 32:
                csv_path = c
                break

    if not csv_path or not os.path.exists(csv_path):
        return generate_realistic_sa_dataset(seed=42)

    df_raw = pd.read_csv(csv_path, nrows=max_rows)
    if len(df_raw) < 5:
        return generate_realistic_sa_dataset(seed=42)

    cols = {c.lower().strip(): c for c in df_raw.columns}

    # Resolve voltage column
    v_col = cols.get("v_rms") or cols.get("voltage_v") or cols.get("voltage") or cols.get("v")
    f_col = cols.get("f_hz") or cols.get("frequency_hz") or cols.get("frequency") or cols.get("f")
    if not v_col or not f_col:
        return generate_realistic_sa_dataset(seed=42)

    v_vals = pd.to_numeric(df_raw[v_col], errors="coerce").fillna(230.0).to_numpy(dtype=float)
    f_vals = pd.to_numeric(df_raw[f_col], errors="coerce").fillna(50.0).to_numpy(dtype=float)

    # Resolve timestamps in seconds
    if "timestamp_s" in cols:
        t_sec = pd.to_numeric(df_raw[cols["timestamp_s"]], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    elif "timestamp" in cols:
        ts_parsed = pd.to_datetime(df_raw[cols["timestamp"]], errors="coerce")
        if ts_parsed.notna().sum() >= 2:
            ts_parsed = ts_parsed.ffill().bfill()
            t_sec = (ts_parsed - ts_parsed.iloc[0]).dt.total_seconds().to_numpy(dtype=float)
        else:
            t_sec = np.arange(len(df_raw), dtype=float) * 2.0
    else:
        t_sec = np.arange(len(df_raw), dtype=float) * 2.0

    # Ensure strictly non-decreasing timestamps
    if len(t_sec) > 1 and np.any(np.diff(t_sec) <= 0):
        t_sec = np.arange(len(df_raw), dtype=float) * 2.0

    # Resolve ZX cycle jitter (or estimate from cycle-to-cycle frequency delta in mHz)
    if "f_cycle_jitter" in cols:
        jitter = pd.to_numeric(df_raw[cols["f_cycle_jitter"]], errors="coerce").fillna(5.5).to_numpy(dtype=float)
    else:
        f_diff_mhz = np.abs(np.diff(f_vals, prepend=f_vals[0])) * 250.0 + 5.0
        jitter = np.clip(f_diff_mhz, 2.0, 500.0)

    v_base = float(np.median(v_vals[(v_vals >= 210.0) & (v_vals <= 245.0)])) if np.any((v_vals >= 210.0) & (v_vals <= 245.0)) else 230.0

    if "target_risk" in cols:
        target = pd.to_numeric(df_raw[cols["target_risk"]], errors="coerce").fillna(0).astype(int).to_numpy()
    elif "outage_label" in cols:
        target = pd.to_numeric(df_raw[cols["outage_label"]], errors="coerce").fillna(0).astype(int).to_numpy()
    else:
        target = ((v_vals < 214.0) | (np.abs(f_vals - 50.0) > 0.35) | (jitter > 40.0)).astype(int)

    df_norm = pd.DataFrame(
        {
            "timestamp_s": t_sec,
            "v_rms": v_vals,
            "f_hz": f_vals,
            "f_cycle_jitter": jitter,
            "v_baseline": np.full(len(df_raw), v_base),
            "target_risk": target,
        }
    )
    return compute_10_features_df(df_norm, default_v_baseline=v_base)


def sync_model_to_github(
    model_version: int,
    cluster_id: str = "global",
    repo_dir: str = REPO_DIR,
    push_remote: bool = False,
) -> Dict[str, Any]:
    """
    Stage updated TinyML model files (`firmware/grid_model.h`, `firmware/features_gen.h`,
    `version.json`, and `windows_trainer/models/cluster_global.{bin,json}`) in Git.
    When `push_remote=True`, commits and pushes to `origin HEAD:main`.
    """
    import subprocess

    logs: List[str] = []
    staged_paths = [
        "firmware/grid_model.h",
        "firmware/features_gen.h",
        "version.json",
        "windows_trainer/models/cluster_global.bin",
        "windows_trainer/models/cluster_global.json",
    ]
    existing_rel = [p for p in staged_paths if os.path.exists(os.path.join(repo_dir, p))]

    def _run_git(args: List[str]) -> Tuple[int, str]:
        proc = subprocess.run(
            ["git"] + args,
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        if out:
            logs.append(out)
        return proc.returncode, out

    rc_check, _ = _run_git(["rev-parse", "--is-inside-work-tree"])
    if rc_check != 0:
        return {"ok": False, "committed": False, "pushed": False, "staged_files": [], "logs": logs}

    if not push_remote:
        # Dry-run verification: verify git status & target artifacts without mutating git history
        rc_st, st_out = _run_git(["status", "--short", "--"] + existing_rel)
        return {
            "ok": rc_st == 0 and len(existing_rel) == len(staged_paths),
            "mode": "dry_run_verified",
            "committed": False,
            "pushed": False,
            "staged_files": existing_rel,
            "git_status_summary": st_out,
            "logs": logs,
        }

    _run_git(["add", "--"] + existing_rel)
    commit_msg = f"Update TinyML model v{model_version} ({cluster_id}) [{time.strftime('%Y-%m-%d %H:%M:%S')}]"
    rc_commit, _ = _run_git(["commit", "-m", commit_msg])
    committed = rc_commit == 0

    pushed = False
    if committed:
        rc_push, _ = _run_git(["push", "origin", "HEAD:main"])
        pushed = rc_push == 0

    return {
        "ok": committed and pushed,
        "mode": "live_push",
        "committed": committed,
        "pushed": pushed,
        "staged_files": existing_rel,
        "logs": logs,
    }


if __name__ == "__main__":
    res = train_regional_model(cluster_id="global", update_cpp_header=True)
    print(
        f"[ml_core] model v{res['model_version']} ({res['n_trees']} trees, "
        f"{res['n_nodes']} nodes, {res['binary_size_bytes']} B) -> {res['metrics']}"
    )
