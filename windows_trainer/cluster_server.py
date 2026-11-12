#!/usr/bin/env python3
"""
GridWatcher v0.3 cluster server and web host.

Exposes three endpoint groups:
  - Public map (`GET /`, `GET /api/v1/public/map`)
  - HMAC-authenticated device ingestion (`POST /api/v1/calibrate`, `/heartbeat`, `/outage-report`)
  - Localhost-only admin routes (`GET /admin`, `/api/v1/admin/*`)
"""

import os
import sys
import time
import json
import hmac
import base64
import hashlib
import threading
from collections import deque
from urllib.parse import urlparse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Dict, List, Optional, Any, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import numpy as np
import pandas as pd
from maintenance_scraper import MaintenanceRegistry
import ml_core

STATE_DIR = os.path.join(SCRIPT_DIR, "server_state")
WEB_DIR = os.path.join(SCRIPT_DIR, "web")
MODELS_DIR = os.path.join(SCRIPT_DIR, "models")

MASTER_DEVICE_SECRET = os.environ.get(
    "GW_MASTER_SECRET",
    "change-me-to-64-char-hex-secret-key-stored-in-esp32-nvs-flash-00",
)

MAX_BODY_BYTES = 262_144  # 256 KB max request payload
RATE_LIMIT_WINDOW_S = 10.0
RATE_LIMIT_MAX_REQ = 120

_PROXY_HEADER_KEYS = frozenset(
    {
        "cf-connecting-ip",
        "cf-ray",
        "cf-visitor",
        "cf-ipcountry",
        "x-forwarded-for",
        "x-real-ip",
        "true-client-ip",
    }
)

_rate_lock = threading.Lock()
_rate_buckets: Dict[str, deque] = {}


def check_rate_limit(client_key: str) -> bool:
    now = time.time()
    with _rate_lock:
        dq = _rate_buckets.get(client_key)
        if dq is None:
            dq = deque()
            _rate_buckets[client_key] = dq
        cutoff = now - RATE_LIMIT_WINDOW_S
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= RATE_LIMIT_MAX_REQ:
            return False
        dq.append(now)
        return True


def derive_device_secret(device_id: str) -> str:
    return MASTER_DEVICE_SECRET


def compute_request_hmac(
    device_id: str,
    timestamp_str: str,
    body_bytes: bytes,
    secret: Optional[str] = None,
) -> str:
    key = (secret or derive_device_secret(device_id)).encode("utf-8")
    msg = f"{device_id}:{timestamp_str}:".encode("utf-8") + body_bytes
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def verify_device_hmac(
    device_id: str,
    timestamp_str: str,
    signature_hex: str,
    body_bytes: bytes,
    max_skew_seconds: int = 300,
) -> Tuple[bool, str]:
    if not device_id or not timestamp_str or not signature_hex:
        return False, "Missing authentication headers (X-Device-ID, X-Timestamp, X-Signature)"
    try:
        ts_val = float(timestamp_str)
    except ValueError:
        return False, "Invalid X-Timestamp header"

    if not np.isfinite(ts_val) or abs(time.time() - ts_val) > max_skew_seconds:
        return False, f"Timestamp outside {max_skew_seconds}s replay window"

    expected = compute_request_hmac(device_id, timestamp_str, body_bytes)
    if not hmac.compare_digest(signature_hex.lower().strip(), expected.lower()):
        return False, "HMAC-SHA256 verification failed"

    return True, "OK"


def compute_lagged_voltage_correlation(
    trace_a: List[Dict[str, float]],
    trace_b: List[Dict[str, float]],
    max_lag_s: float = 5.0,
) -> float:
    """
    Max Pearson correlation r_V between two voltage traces across a +/-5s lag search.
    """
    if len(trace_a) < 6 or len(trace_b) < 6:
        return 0.0

    ta = np.array([float(p.get("t", i * 2)) for i, p in enumerate(trace_a)], dtype=float)
    va = np.array([float(p.get("v", p.get("v_rms", 230.0))) for p in trace_a], dtype=float)
    tb = np.array([float(p.get("t", i * 2)) for i, p in enumerate(trace_b)], dtype=float)
    vb = np.array([float(p.get("v", p.get("v_rms", 230.0))) for p in trace_b], dtype=float)

    va_dev = va - np.mean(va)
    vb_dev = vb - np.mean(vb)

    if np.std(va_dev) < 1e-3 or np.std(vb_dev) < 1e-3:
        return 0.0

    ta_rel = ta - ta[0]
    tb_rel = tb - tb[0]
    common_max_t = min(ta_rel[-1], tb_rel[-1])
    if common_max_t < 10.0:
        m = min(len(va_dev), len(vb_dev))
        c = np.corrcoef(va_dev[:m], vb_dev[:m])[0, 1]
        return float(0.0 if np.isnan(c) else c)

    grid_t = np.linspace(0.0, common_max_t, num=min(60, int(common_max_t) + 1))
    va_interp = np.interp(grid_t, ta_rel, va_dev)

    best_r = -1.0
    for lag in np.linspace(-max_lag_s, max_lag_s, 11):
        vb_interp = np.interp(grid_t + lag, tb_rel, vb_dev)
        if np.std(va_interp) > 1e-4 and np.std(vb_interp) > 1e-4:
            r = float(np.corrcoef(va_interp, vb_interp)[0, 1])
            if not np.isnan(r) and r > best_r:
                best_r = r

    return max(0.0, round(best_r, 4))


class GridWatcherClusterState:
    def __init__(self, state_dir: str = STATE_DIR):
        self._lock = threading.RLock()
        self.state_dir = state_dir
        os.makedirs(self.state_dir, exist_ok=True)
        os.makedirs(MODELS_DIR, exist_ok=True)
        self.maintenance = MaintenanceRegistry(os.path.join(self.state_dir, "maintenance_windows.json"))
        self.devices: Dict[str, Dict[str, Any]] = self._load_json(os.path.join(self.state_dir, "devices.json"), {})
        self.clusters: Dict[str, Dict[str, Any]] = self._load_json(os.path.join(self.state_dir, "clusters.json"), {})
        self.events: List[Dict[str, Any]] = self._load_json(os.path.join(self.state_dir, "events.json"), [])
        self._ensure_default_seed()

    def _load_json(self, path: str, default: Any) -> Any:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return default

    def save(self) -> None:
        with self._lock:
            with open(os.path.join(self.state_dir, "devices.json"), "w", encoding="utf-8") as f:
                json.dump(self.devices, f, indent=2)
            with open(os.path.join(self.state_dir, "clusters.json"), "w", encoding="utf-8") as f:
                json.dump(self.clusters, f, indent=2)
            with open(os.path.join(self.state_dir, "events.json"), "w", encoding="utf-8") as f:
                json.dump(self.events[-200:], f, indent=2)

    def append_telemetry_csv(
        self,
        device_id: str,
        cluster_id: str,
        samples: List[Dict[str, Any]],
        event_type: str = "NORMAL",
        train_eligible: bool = True,
    ) -> int:
        if not samples:
            return 0
        csv_path = os.path.join(self.state_dir, "collected_telemetry.csv")
        write_header = not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0
        rows_written = 0
        with self._lock:
            with open(csv_path, "a", encoding="utf-8") as f:
                if write_header:
                    f.write("timestamp_s,device_id,cluster_id,v_rms,f_hz,f_cycle_jitter,event_type,target_risk\n")
                for idx, s in enumerate(samples):
                    t_s = float(s.get("timestamp_s", s.get("t", idx * 2.0)))
                    v_val = float(s.get("v_rms", s.get("v", s.get("voltage", 230.0))))
                    f_val = float(s.get("f_hz", s.get("f", s.get("frequency", 50.0))))
                    jit_val = float(s.get("f_cycle_jitter", s.get("jitter", 5.5)))
                    lbl = 1 if (train_eligible and (v_val < 222.0 or abs(f_val - 50.0) > 0.15 or jit_val > 25.0)) else 0
                    f.write(
                        f"{t_s:.2f},{device_id},{cluster_id},{v_val:.3f},{f_val:.4f},{jit_val:.2f},{event_type},{lbl}\n"
                    )
                    rows_written += 1
        return rows_written

    def export_telemetry_csv_bytes(self) -> bytes:
        csv_path = os.path.join(self.state_dir, "collected_telemetry.csv")
        if os.path.exists(csv_path) and os.path.getsize(csv_path) > 32:
            with open(csv_path, "rb") as f:
                return f.read()
        root_ds = os.path.join(ml_core.REPO_DIR, "gridwatcher_dataset.csv")
        if os.path.exists(root_ds):
            with open(root_ds, "rb") as f:
                return f.read()
        df_seed = ml_core.generate_realistic_sa_dataset(seed=42)
        return df_seed.to_csv(index=False).encode("utf-8")

    def get_cluster_model_binary(self, cluster_id: str) -> bytes:
        safe_cid = ml_core.sanitize_identifier(cluster_id, "global")
        c_info = self.clusters.get(safe_cid, {})
        model_id = ml_core.sanitize_identifier(str(c_info.get("model_id", "global")), "global")
        bin_path = os.path.join(MODELS_DIR, f"cluster_{model_id}.bin")
        if not os.path.exists(bin_path):
            bin_path = os.path.join(MODELS_DIR, "cluster_global.bin")
        with open(bin_path, "rb") as bf:
            return bf.read()

    def _ensure_default_seed(self) -> None:
        global_json = os.path.join(MODELS_DIR, "cluster_global.json")
        if not os.path.exists(global_json):
            ml_core.train_regional_model(cluster_id="global", update_cpp_header=True)

        if not self.clusters:
            with open(global_json, "r", encoding="utf-8") as f:
                g_meta = json.load(f)
            self.clusters["CLUSTER-EKU-GERMISTON-01"] = {
                "cluster_id": "CLUSTER-EKU-GERMISTON-01",
                "name": "Ekurhuleni - Germiston 11kV Feeder A",
                "suburb": "Germiston",
                "cell_lacs": [1041, 1042],
                "model_version": g_meta.get("model_version", 41),
                "model_id": "global",
                "adaptation_mode": "SUPERVISED_ACTIVE",
                "verified_outages_count": 6,
                "devices": ["GW-ZA-EKU-001", "GW-ZA-EKU-002"],
                "metrics": g_meta.get("metrics", {}),
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.clusters["CLUSTER-EKU-BOKSBURG-02"] = {
                "cluster_id": "CLUSTER-EKU-BOKSBURG-02",
                "name": "Ekurhuleni - Boksburg North Substation",
                "suburb": "Boksburg",
                "cell_lacs": [1042, 1043],
                "model_version": g_meta.get("model_version", 41),
                "model_id": "global",
                "adaptation_mode": "COLD_START_LAYER2A",
                "verified_outages_count": 1,
                "devices": ["GW-ZA-EKU-003"],
                "metrics": g_meta.get("metrics", {}),
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }

        if not self.devices:
            now = time.time()
            self.devices["GW-ZA-EKU-001"] = {
                "device_id": "GW-ZA-EKU-001",
                "name": "Germiston Unit 1",
                "suburb": "Germiston",
                "lat": -26.2178,
                "lon": 28.1675,
                "cell_lac": 1041,
                "cell_id": 44012,
                "cluster_id": "CLUSTER-EKU-GERMISTON-01",
                "v_rms": 230.2,
                "v_baseline": 230.0,
                "f_hz": 50.01,
                "f_cycle_jitter": 5.2,
                "risk_score": 4.2,
                "status": "ONLINE_NORMAL",
                "mains_pgood_ok": True,
                "battery_pct": 98,
                "model_version": 41,
                "correlation_with_cluster": 0.96,
                "last_seen_epoch": now,
                "recent_trace": [
                    {"t": i * 2, "v": float(230.0 + 0.5 * np.sin(i * 0.3)), "f": 50.0}
                    for i in range(20)
                ],
            }
            self.devices["GW-ZA-EKU-002"] = {
                "device_id": "GW-ZA-EKU-002",
                "name": "Germiston Unit 2",
                "suburb": "Germiston",
                "lat": -26.2215,
                "lon": 28.1720,
                "cell_lac": 1041,
                "cell_id": 44012,
                "cluster_id": "CLUSTER-EKU-GERMISTON-01",
                "v_rms": 229.4,
                "v_baseline": 229.2,
                "f_hz": 50.01,
                "f_cycle_jitter": 5.5,
                "risk_score": 4.5,
                "status": "ONLINE_NORMAL",
                "mains_pgood_ok": True,
                "battery_pct": 95,
                "model_version": 41,
                "correlation_with_cluster": 0.96,
                "last_seen_epoch": now,
                "recent_trace": [
                    {"t": i * 2, "v": float(229.2 + 0.5 * np.sin(i * 0.3)), "f": 50.0}
                    for i in range(20)
                ],
            }
            self.devices["GW-ZA-EKU-003"] = {
                "device_id": "GW-ZA-EKU-003",
                "name": "Boksburg Unit 3",
                "suburb": "Boksburg",
                "lat": -26.2125,
                "lon": 28.2510,
                "cell_lac": 1043,
                "cell_id": 51008,
                "cluster_id": "CLUSTER-EKU-BOKSBURG-02",
                "v_rms": 224.8,
                "v_baseline": 225.0,
                "f_hz": 49.98,
                "f_cycle_jitter": 7.1,
                "risk_score": 8.0,
                "status": "ONLINE_NORMAL",
                "mains_pgood_ok": True,
                "battery_pct": 100,
                "model_version": 41,
                "correlation_with_cluster": 1.0,
                "last_seen_epoch": now,
                "recent_trace": [
                    {"t": i * 2, "v": float(225.0 + 0.4 * np.cos(i * 0.25)), "f": 49.99}
                    for i in range(20)
                ],
            }
            self.save()

    def get_cluster_model_payload(self, cluster_id: str) -> Dict[str, Any]:
        safe_cid = ml_core.sanitize_identifier(cluster_id, "global")
        c_info = self.clusters.get(safe_cid, {})
        model_id = ml_core.sanitize_identifier(str(c_info.get("model_id", "global")), "global")
        json_path = os.path.join(MODELS_DIR, f"cluster_{model_id}.json")
        bin_path = os.path.join(MODELS_DIR, f"cluster_{model_id}.bin")
        if not os.path.exists(json_path):
            json_path = os.path.join(MODELS_DIR, "cluster_global.json")
            bin_path = os.path.join(MODELS_DIR, "cluster_global.bin")

        with open(json_path, "r", encoding="utf-8") as jf:
            meta = json.load(jf)
        b64_bin = ""
        if os.path.exists(bin_path):
            with open(bin_path, "rb") as bf:
                b64_bin = base64.b64encode(bf.read()).decode("ascii")

        return {
            "cluster_id": safe_cid,
            "model_version": meta["model_version"],
            "schema_version": meta["schema_version"],
            "feature_hash": meta["feature_hash"],
            "n_trees": meta["n_trees"],
            "n_nodes": meta["n_nodes"],
            "binary_size_bytes": meta["binary_size_bytes"],
            "binary_payload_b64": b64_bin,
            "tree_roots": meta["tree_roots"],
            "flat_nodes": meta["flat_nodes"],
        }

    def calibrate_and_assign_cluster(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            device_id = ml_core.sanitize_identifier(str(payload.get("device_id", "")), "GW-UNKNOWN")
            cell_lac = int(payload.get("cell_lac", 1041))
            cell_id = int(payload.get("cell_id", 44000))
            suburb = str(payload.get("suburb", "Ekurhuleni"))[:64]
            lat = float(payload.get("lat", -26.215 + (hash(device_id) % 40 - 20) * 0.001))
            lon = float(payload.get("lon", 28.180 + (hash(device_id) % 50 - 25) * 0.001))
            trace = payload.get("trace", [])

            v_vals = [float(p.get("v", p.get("v_rms", 230.0))) for p in trace] if trace else [230.0]
            v_baseline = float(payload.get("v_baseline", np.median(v_vals)))

            best_cluster_id = None
            best_r = 0.0

            for dev_id, other in self.devices.items():
                if dev_id == device_id:
                    continue
                other_lac = int(other.get("cell_lac", 0))
                if abs(other_lac - cell_lac) > 2:
                    continue
                other_trace = other.get("recent_trace", [])
                r_v = compute_lagged_voltage_correlation(trace, other_trace)
                if r_v >= 0.90 and r_v > best_r:
                    best_r = r_v
                    best_cluster_id = other.get("cluster_id")

            if best_cluster_id and best_cluster_id in self.clusters:
                cluster = self.clusters[best_cluster_id]
                if device_id not in cluster["devices"]:
                    cluster["devices"].append(device_id)
                assigned_mode = "MATCHED_EXISTING_CLUSTER"
            else:
                suburb_tag = ml_core.sanitize_identifier(suburb.upper().replace(" ", "")[:6], "REG")
                best_cluster_id = f"CLUSTER-{suburb_tag}-{cell_lac}"
                best_r = 1.0
                if best_cluster_id not in self.clusters:
                    g_payload = self.get_cluster_model_payload("global")
                    self.clusters[best_cluster_id] = {
                        "cluster_id": best_cluster_id,
                        "name": f"{suburb} Regional Feeder (LAC {cell_lac})",
                        "suburb": suburb,
                        "cell_lacs": [cell_lac],
                        "model_version": g_payload["model_version"],
                        "model_id": "global",
                        "adaptation_mode": "COLD_START_LAYER2A",
                        "verified_outages_count": 0,
                        "devices": [device_id],
                        "metrics": {},
                        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    assigned_mode = "SPAWNED_NEW_COLD_START_CLUSTER"
                else:
                    if device_id not in self.clusters[best_cluster_id]["devices"]:
                        self.clusters[best_cluster_id]["devices"].append(device_id)
                    assigned_mode = "JOINED_LAC_CLUSTER"

            model_bundle = self.get_cluster_model_payload(best_cluster_id)
            self.devices[device_id] = {
                "device_id": device_id,
                "name": str(payload.get("name", f"GridWatcher {device_id}"))[:80],
                "suburb": suburb,
                "lat": lat,
                "lon": lon,
                "cell_lac": cell_lac,
                "cell_id": cell_id,
                "cluster_id": best_cluster_id,
                "v_rms": float(v_vals[-1]),
                "v_baseline": round(v_baseline, 2),
                "f_hz": float(trace[-1].get("f", 50.0)) if trace else 50.0,
                "f_cycle_jitter": float(trace[-1].get("jitter", 5.0)) if trace else 5.0,
                "risk_score": 5.0,
                "status": "ONLINE_NORMAL",
                "mains_pgood_ok": True,
                "battery_pct": int(payload.get("battery_pct", 100)),
                "model_version": model_bundle["model_version"],
                "correlation_with_cluster": round(best_r, 3),
                "last_seen_epoch": time.time(),
                "recent_trace": trace[-60:] if trace else [],
            }
            self.save()

            return {
                "status": "calibrated",
                "device_id": device_id,
                "cluster_id": best_cluster_id,
                "assignment_mode": assigned_mode,
                "correlation_r": round(best_r, 3),
                "learned_v_baseline": round(v_baseline, 2),
                "model": model_bundle,
            }

    def process_heartbeat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            device_id = ml_core.sanitize_identifier(str(payload.get("device_id", "")), "GW-UNKNOWN")
            dev = self.devices.get(device_id)
            if not dev:
                return self.calibrate_and_assign_cluster(payload)

            v_rms = float(payload.get("v_rms", dev.get("v_rms", 230.0)))
            f_hz = float(payload.get("f_hz", dev.get("f_hz", 50.0)))
            jitter = float(payload.get("f_cycle_jitter", dev.get("f_cycle_jitter", 5.0)))
            pgood_ok = bool(payload.get("mains_pgood_ok", v_rms >= 100.0))
            client_model_ver = int(payload.get("model_version", dev.get("model_version", 0)))

            if "trace" in payload and payload["trace"]:
                dev["recent_trace"] = payload["trace"][-60:]

            cluster_id = dev["cluster_id"]
            model_bundle = self.get_cluster_model_payload(cluster_id)

            trace = dev.get("recent_trace", [])
            if len(trace) >= 2:
                ts_arr = np.array([float(p.get("t", idx * 2)) for idx, p in enumerate(trace)], dtype=float)
                v_arr = np.array([float(p.get("v", p.get("v_rms", v_rms))) for p in trace], dtype=float)
                f_arr = np.array([float(p.get("f", p.get("f_hz", f_hz))) for p in trace], dtype=float)
                feat_vec = ml_core.compute_single_window_features(
                    ts_arr, v_arr, f_arr, v_baseline=float(dev.get("v_baseline", 230.0)), f_cycle_jitter_override=jitter
                )
            else:
                feat_vec = np.array(
                    [v_rms, v_rms - float(dev.get("v_baseline", 230.0)), f_hz, jitter, 0.0, 0.0, 0.25, 0.02, 0.0, 0.0],
                    dtype=np.float32,
                )

            l2a_risk = ml_core.compute_unsupervised_layer2a_risk(feat_vec)
            l2b_risk, _ = ml_core.evaluate_flat_model_single(
                feat_vec, model_bundle["flat_nodes"], model_bundle["tree_roots"]
            )
            risk_score = float(payload.get("risk_score", max(l2a_risk, l2b_risk)))

            maint_match = self.maintenance.check_active_or_upcoming(
                suburb=dev.get("suburb"), cell_lac=dev.get("cell_lac")
            )

            if not pgood_ok or v_rms < 100.0:
                status_str = "MAINS_LOST_ON_BATTERY" if not maint_match else "SCHEDULED_MAINTENANCE"
            elif risk_score >= 70.0:
                status_str = "CRITICAL_PRE_OUTAGE_RISK"
            elif risk_score >= 40.0:
                status_str = "ELEVATED_RISK"
            elif maint_match:
                status_str = "MAINTENANCE_ADVISORY"
            else:
                status_str = "ONLINE_NORMAL"

            dev.update(
                {
                    "v_rms": round(v_rms, 2),
                    "f_hz": round(f_hz, 3),
                    "f_cycle_jitter": round(jitter, 2),
                    "mains_pgood_ok": pgood_ok,
                    "risk_score": round(risk_score, 1),
                    "status": status_str,
                    "battery_pct": int(payload.get("battery_pct", dev.get("battery_pct", 98))),
                    "last_seen_epoch": time.time(),
                }
            )

            update_needed = model_bundle["model_version"] > client_model_ver
            if update_needed:
                dev["model_version"] = model_bundle["model_version"]

            self.save()

            resp = {
                "status": "ok",
                "device_id": device_id,
                "cluster_id": cluster_id,
                "computed_risk_pct": round(risk_score, 1),
                "grid_status": status_str,
                "scheduled_maintenance": maint_match,
                "update_available": update_needed,
            }
            if update_needed:
                resp["model"] = model_bundle
            return resp

    def process_outage_report(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            device_id = ml_core.sanitize_identifier(str(payload.get("device_id", "")), "GW-UNKNOWN")
            dev = self.devices.get(device_id)
            if not dev:
                self.calibrate_and_assign_cluster(payload)
                dev = self.devices[device_id]

            cluster_id = dev["cluster_id"]
            outage_epoch = float(payload.get("outage_timestamp_epoch", time.time() - 120.0))
            drop_duration_ms = float(payload.get("drop_duration_ms", 20.0))
            pre_cell_id = payload.get("pre_cell_id", dev.get("cell_id"))
            post_cell_id = payload.get("post_cell_id", dev.get("cell_id"))
            pre_v_base = float(payload.get("pre_v_baseline", dev.get("v_baseline", 230.0)))
            post_v_base = float(payload.get("post_v_baseline", dev.get("v_baseline", 230.0)))

            # Co-occurrence check across recent outage reports (+/- 5 seconds)
            co_occurring_siblings = []
            for ev in reversed(self.events[-40:]):
                if ev.get("device_id") != device_id:
                    if abs(float(ev.get("outage_epoch", 0)) - outage_epoch) <= 5.0:
                        co_occurring_siblings.append(ev["device_id"])

            if co_occurring_siblings:
                sibling_id = co_occurring_siblings[0]
                sib_dev = self.devices.get(sibling_id)
                if sib_dev and sib_dev.get("cluster_id") != cluster_id:
                    cluster_id = sib_dev["cluster_id"]
                    dev["cluster_id"] = cluster_id
                    if device_id not in self.clusters[cluster_id]["devices"]:
                        self.clusters[cluster_id]["devices"].append(device_id)

            maint_window = self.maintenance.check_active_or_upcoming(
                suburb=dev.get("suburb"),
                cell_lac=dev.get("cell_lac"),
                timestamp_epoch=outage_epoch,
            )

            samples = payload.get("samples", [])
            if samples:
                df_trace = pd.DataFrame(samples)
            else:
                df_trace = pd.DataFrame(
                    {
                        "timestamp_s": [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
                        "v_rms": [230.0, 230.0, 230.0, 230.0, 230.0, 230.0, 230.0],
                        "f_hz": [50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0],
                    }
                )

            classification = ml_core.classify_outage_event(
                df_trace,
                drop_duration_ms=drop_duration_ms,
                pre_cell_id=str(pre_cell_id),
                post_cell_id=str(post_cell_id),
                pre_v_baseline=pre_v_base,
                post_v_baseline=post_v_base,
                scheduled_maintenance_match=(maint_window is not None),
                sibling_co_occurrence=(len(co_occurring_siblings) > 0),
            )

            event_record = {
                "event_id": f"EVT-{int(time.time() * 1000) % 10000000:07d}",
                "device_id": device_id,
                "cluster_id": cluster_id,
                "suburb": dev.get("suburb", "Ekurhuleni"),
                "outage_epoch": outage_epoch,
                "reported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "event_type": classification["event_type"],
                "train_eligible": classification["train_eligible"],
                "relocated": classification["relocated"],
                "reason": classification["reason"],
                "co_occurring_siblings": co_occurring_siblings,
                "metrics": classification.get("metrics", {}),
                "retrained_model_version": None,
                "csv_rows_logged": 0,
                "github_sync": None,
            }

            if samples:
                event_record["csv_rows_logged"] = self.append_telemetry_csv(
                    device_id=device_id,
                    cluster_id=cluster_id,
                    samples=samples,
                    event_type=classification["event_type"],
                    train_eligible=classification["train_eligible"],
                )

            if classification["relocated"]:
                dev["cell_id"] = post_cell_id
                dev["v_baseline"] = post_v_base

            if classification["train_eligible"]:
                cluster = self.clusters[cluster_id]
                cluster["verified_outages_count"] = int(cluster.get("verified_outages_count", 0)) + 1
                new_ver = int(cluster.get("model_version", 41)) + 1

                base_df = ml_core.generate_realistic_sa_dataset(seed=42 + new_ver)
                retrained_meta = ml_core.train_regional_model(
                    df_train_raw=base_df,
                    cluster_id=cluster_id,
                    model_version=new_ver,
                    update_cpp_header=True,
                )
                cluster["model_id"] = cluster_id
                cluster["model_version"] = retrained_meta["model_version"]
                cluster["adaptation_mode"] = "SUPERVISED_ACTIVE"
                cluster["metrics"] = retrained_meta["metrics"]
                cluster["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                dev["model_version"] = retrained_meta["model_version"]
                event_record["retrained_model_version"] = retrained_meta["model_version"]
                auto_push = os.environ.get("GW_AUTO_GIT_PUSH", "0") == "1"
                event_record["github_sync"] = ml_core.sync_model_to_github(
                    model_version=retrained_meta["model_version"],
                    cluster_id=cluster_id,
                    push_remote=auto_push,
                )

            self.events.append(event_record)
            self.save()

            model_bundle = self.get_cluster_model_payload(cluster_id)
            return {
                "status": "processed",
                "event": event_record,
                "cluster_id": cluster_id,
                "model_retrained": classification["train_eligible"],
                "active_model": model_bundle,
            }

    def get_public_map_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            public_devices = []
            for d in self.devices.values():
                public_devices.append(
                    {
                        "device_id": d["device_id"],
                        "name": d.get("name", d["device_id"]),
                        "suburb": d.get("suburb", "Ekurhuleni"),
                        "lat": d.get("lat", -26.2178),
                        "lon": d.get("lon", 28.1675),
                        "cluster_id": d.get("cluster_id"),
                        "v_rms": d.get("v_rms", 230.0),
                        "v_baseline": d.get("v_baseline", 230.0),
                        "f_hz": d.get("f_hz", 50.0),
                        "f_cycle_jitter": d.get("f_cycle_jitter", 5.0),
                        "risk_score": d.get("risk_score", 0.0),
                        "status": d.get("status", "ONLINE_NORMAL"),
                        "mains_pgood_ok": d.get("mains_pgood_ok", True),
                        "battery_pct": d.get("battery_pct", 100),
                        "model_version": d.get("model_version", 41),
                        "correlation_with_cluster": d.get("correlation_with_cluster", 1.0),
                    }
                )

            return {
                "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "schema_version": ml_core.GW_SCHEMA_VERSION,
                "feature_hash": f"0x{ml_core.GW_FEATURE_HASH:08X}",
                "devices": public_devices,
                "clusters": list(self.clusters.values()),
                "maintenance_windows": self.maintenance.list_windows(),
                "recent_events": [
                    {
                        "event_id": e["event_id"],
                        "device_id": e["device_id"],
                        "suburb": e.get("suburb"),
                        "event_type": e["event_type"],
                        "reported_at": e["reported_at"],
                        "reason": e["reason"],
                    }
                    for e in reversed(self.events[-15:])
                ],
            }


SERVER_STATE = GridWatcherClusterState()


def dispatch_http_request(
    method: str,
    raw_path: str,
    headers: Dict[str, str],
    body_bytes: bytes = b"",
    client_ip: str = "127.0.0.1",
    state: Optional[GridWatcherClusterState] = None,
) -> Tuple[int, str, bytes]:
    """
    HTTP request dispatcher returning (status_code, content_type, response_bytes).
    """
    st = state or SERVER_STATE
    parsed = urlparse(raw_path)
    path = parsed.path

    norm_headers = {k.lower(): v for k, v in (headers or {}).items()}

    def _json_resp(code: int, obj: Any) -> Tuple[int, str, bytes]:
        return code, "application/json; charset=utf-8", json.dumps(obj).encode("utf-8")

    if len(body_bytes) > MAX_BODY_BYTES:
        return _json_resp(413, {"detail": f"Payload exceeds {MAX_BODY_BYTES} byte limit"})

    # Determine effective origin IP for rate-limiting and tunnel detection
    forwarded_ip = (
        norm_headers.get("cf-connecting-ip")
        or norm_headers.get("x-real-ip")
        or norm_headers.get("x-forwarded-for", "").split(",")[0].strip()
    )
    effective_ip = forwarded_ip or client_ip

    if not check_rate_limit(effective_ip):
        return _json_resp(429, {"detail": "Rate limit exceeded"})

    def _is_admin_allowed() -> bool:
        # Reject any request carrying reverse-proxy / Cloudflare headers, even if the
        # local cloudflared daemon connects over 127.0.0.1.
        if any(h in norm_headers for h in _PROXY_HEADER_KEYS):
            return False
        return client_ip in ("127.0.0.1", "::1", "localhost")

    # Public routes
    if method == "GET" and path == "/":
        index_path = os.path.join(WEB_DIR, "index.html")
        if os.path.exists(index_path):
            with open(index_path, "rb") as f:
                return 200, "text/html; charset=utf-8", f.read()
        return 200, "text/html; charset=utf-8", b"<h1>GridWatcher Public Grid Map</h1>"

    if method == "GET" and path == "/api/v1/public/map":
        return _json_resp(200, st.get_public_map_snapshot())

    if method == "GET" and path in ("/api/telemetry.csv", "/api/v1/telemetry.csv"):
        return 200, "text/csv; charset=utf-8", st.export_telemetry_csv_bytes()

    if method == "GET" and path in ("/version.json", "/api/v1/version"):
        v_obj: Dict[str, Any] = {"version": 41, "schema_version": ml_core.GW_SCHEMA_VERSION}
        if os.path.exists(ml_core.VERSION_JSON_PATH):
            try:
                with open(ml_core.VERSION_JSON_PATH, "r", encoding="utf-8") as vf:
                    v_obj = json.load(vf)
            except Exception:
                pass
        v_obj["clusters"] = {
            cid: c.get("model_version", 41) for cid, c in st.clusters.items()
        }
        return _json_resp(200, v_obj)

    if method == "GET" and path.startswith("/api/v1/model/"):
        raw_target = path[len("/api/v1/model/") :]
        if raw_target.endswith(".bin"):
            cid = raw_target[:-4]
            return 200, "application/octet-stream", st.get_cluster_model_binary(cid)
        return _json_resp(200, st.get_cluster_model_payload(raw_target))

    # Device ingestion routes (HMAC-SHA256 authenticated)
    if method == "POST" and path in ("/api/v1/calibrate", "/api/v1/heartbeat", "/api/v1/outage-report"):
        dev_id = norm_headers.get("x-device-id", "")
        ts_str = norm_headers.get("x-timestamp", "")
        sig_hex = norm_headers.get("x-signature", "")
        ok, reason = verify_device_hmac(dev_id, ts_str, sig_hex, body_bytes)
        if not ok:
            return _json_resp(401, {"detail": reason})
        try:
            payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception:
            return _json_resp(400, {"detail": "Invalid JSON payload"})

        if not isinstance(payload, dict):
            return _json_resp(400, {"detail": "JSON root must be an object"})

        # Enforce header/body device_id consistency
        body_dev_id = str(payload.get("device_id", dev_id))
        if body_dev_id != dev_id:
            return _json_resp(401, {"detail": "X-Device-ID header does not match payload device_id"})
        payload["device_id"] = dev_id

        if path == "/api/v1/calibrate":
            return _json_resp(200, st.calibrate_and_assign_cluster(payload))
        if path == "/api/v1/heartbeat":
            return _json_resp(200, st.process_heartbeat(payload))
        if path == "/api/v1/outage-report":
            return _json_resp(200, st.process_outage_report(payload))

    # Localhost-only admin routes
    if path == "/admin" or path.startswith("/api/v1/admin/"):
        if not _is_admin_allowed():
            return _json_resp(
                403,
                {"detail": "Forbidden: /admin is restricted to direct localhost connections."},
            )

        if method == "GET" and path == "/admin":
            admin_path = os.path.join(WEB_DIR, "admin.html")
            if os.path.exists(admin_path):
                with open(admin_path, "rb") as f:
                    return 200, "text/html; charset=utf-8", f.read()
            return 200, "text/html; charset=utf-8", b"<h1>GridWatcher Admin</h1>"

        if method == "GET" and path == "/api/v1/admin/overview":
            return _json_resp(
                200,
                {
                    "devices": st.devices,
                    "clusters": st.clusters,
                    "events": list(reversed(st.events[-50:])),
                    "maintenance_windows": st.maintenance.list_windows(),
                    "feature_names": ml_core.FEATURE_NAMES,
                    "feature_hash": f"0x{ml_core.GW_FEATURE_HASH:08X}",
                },
            )

        try:
            body_obj = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception:
            return _json_resp(400, {"detail": "Invalid JSON body"})

        if method == "POST" and path == "/api/v1/admin/retrain":
            cluster_id = ml_core.sanitize_identifier(str(body_obj.get("cluster_id", "global")), "global")
            meta = ml_core.train_regional_model(cluster_id=cluster_id, update_cpp_header=True)
            if cluster_id in st.clusters:
                st.clusters[cluster_id]["model_id"] = cluster_id
                st.clusters[cluster_id]["model_version"] = meta["model_version"]
                st.clusters[cluster_id]["metrics"] = meta["metrics"]
                st.clusters[cluster_id]["updated_at"] = meta["build_time"]
                st.save()
            git_res = ml_core.sync_model_to_github(
                model_version=meta["model_version"],
                cluster_id=cluster_id,
                push_remote=bool(body_obj.get("push_github", False)),
            )
            return _json_resp(200, {"status": "retrained", "model_meta": meta, "github_sync": git_res})

        if method == "POST" and path == "/api/v1/admin/github-sync":
            ver = int(body_obj.get("model_version", 41))
            cid = ml_core.sanitize_identifier(str(body_obj.get("cluster_id", "global")), "global")
            push_flag = bool(body_obj.get("push_remote", False))
            git_res = ml_core.sync_model_to_github(model_version=ver, cluster_id=cid, push_remote=push_flag)
            return _json_resp(200, git_res)

        if method == "POST" and path == "/api/v1/admin/override-event":
            event_id = str(body_obj.get("event_id", ""))
            new_type = str(body_obj.get("event_type", ""))
            for ev in st.events:
                if ev.get("event_id") == event_id:
                    ev["event_type"] = new_type
                    ev["train_eligible"] = (new_type == ml_core.EVENT_PRECURSOR_OUTAGE)
                    ev["reason"] = f"Manual override -> {new_type}"
                    st.save()
                    return _json_resp(200, {"status": "updated", "event": ev})
            return _json_resp(404, {"detail": "Event not found"})

        if method == "POST" and path == "/api/v1/admin/maintenance-notice":
            raw_text = str(body_obj.get("raw_text", "")).strip()
            if not raw_text:
                return _json_resp(400, {"detail": "raw_text required"})
            entry = st.maintenance.parse_social_notice(
                raw_text=raw_text[:1000],
                start_epoch=body_obj.get("start_epoch"),
                end_epoch=body_obj.get("end_epoch"),
                source=str(body_obj.get("source", "City of Ekurhuleni (@CoE_Call_Centre)"))[:120],
            )
            return _json_resp(200, {"status": "added", "window": entry})

        if method == "POST" and path == "/api/v1/admin/shenzhen-replay":
            device_id = ml_core.sanitize_identifier(str(body_obj.get("device_id", "GW-ZA-EKU-001")), "GW-ZA-EKU-001")
            stage = str(body_obj.get("stage", "precursor_warning"))
            dev = st.devices.get(device_id)
            if not dev:
                return _json_resp(404, {"detail": f"Device {device_id} not found"})

            if stage == "precursor_warning":
                dev["v_rms"] = 208.4
                dev["f_hz"] = 49.42
                dev["f_cycle_jitter"] = 112.5
                dev["risk_score"] = 88.6
                dev["mains_pgood_ok"] = True
                dev["status"] = "CRITICAL_PRE_OUTAGE_RISK"
            elif stage == "blackout":
                dev["v_rms"] = 0.0
                dev["f_hz"] = 0.0
                dev["f_cycle_jitter"] = 0.0
                dev["risk_score"] = 100.0
                dev["mains_pgood_ok"] = False
                dev["status"] = "MAINS_LOST_ON_BATTERY"
            else:
                dev["v_rms"] = dev.get("v_baseline", 230.0)
                dev["f_hz"] = 50.00
                dev["f_cycle_jitter"] = 5.1
                dev["risk_score"] = 4.0
                dev["mains_pgood_ok"] = True
                dev["status"] = "ONLINE_NORMAL"

            dev["last_seen_epoch"] = time.time()
            st.save()
            return _json_resp(200, {"status": "replayed", "stage": stage, "device": dev})

    return _json_resp(404, {"detail": f"Not found: {method} {path}"})


class GridWatcherHTTPRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _handle(self, method: str) -> None:
        try:
            content_len = int(self.headers.get("Content-Length", 0))
        except ValueError:
            content_len = 0

        if content_len > MAX_BODY_BYTES:
            resp_bytes = json.dumps({"detail": f"Payload exceeds {MAX_BODY_BYTES} byte limit"}).encode("utf-8")
            self.send_response(413)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(resp_bytes)
            return

        body_bytes = self.rfile.read(content_len) if content_len > 0 else b""
        hdr_dict = {k: v for k, v in self.headers.items()}
        client_ip = self.client_address[0] if self.client_address else "127.0.0.1"

        code, content_type, resp_bytes = dispatch_http_request(
            method, self.path, hdr_dict, body_bytes, client_ip=client_ip
        )
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(resp_bytes)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(resp_bytes)

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")


class LocalTestResponse:
    def __init__(self, status_code: int, content_type: str, body: bytes):
        self.status_code = status_code
        self.content_type = content_type
        self.content = body
        self.text = body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)


class LocalTestClient:
    def __init__(self, state: Optional[GridWatcherClusterState] = None, client_ip: str = "127.0.0.1"):
        self.state = state or SERVER_STATE
        self.client_ip = client_ip

    def get(self, path: str, headers: Optional[Dict[str, str]] = None, client_ip: Optional[str] = None) -> LocalTestResponse:
        code, ctype, body = dispatch_http_request(
            "GET", path, headers or {}, b"", client_ip=client_ip or self.client_ip, state=self.state
        )
        return LocalTestResponse(code, ctype, body)

    def post(
        self,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        raw_body: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
        client_ip: Optional[str] = None,
        sign_as_device: Optional[str] = None,
    ) -> LocalTestResponse:
        body_bytes = raw_body if raw_body is not None else (json.dumps(json_data).encode("utf-8") if json_data is not None else b"")
        hdrs = dict(headers or {})
        if sign_as_device:
            ts_str = f"{time.time():.3f}"
            sig = compute_request_hmac(sign_as_device, ts_str, body_bytes)
            hdrs["X-Device-ID"] = sign_as_device
            hdrs["X-Timestamp"] = ts_str
            hdrs["X-Signature"] = sig
        code, ctype, body = dispatch_http_request(
            "POST", path, hdrs, body_bytes, client_ip=client_ip or self.client_ip, state=self.state
        )
        return LocalTestResponse(code, ctype, body)


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), GridWatcherHTTPRequestHandler)
    print(f"[server] listening on http://{host}:{port}")
    print(f"[server] public map:  http://{host}:{port}/")
    print(f"[server] local admin: http://{host}:{port}/admin")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
