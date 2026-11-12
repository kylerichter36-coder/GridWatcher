#!/usr/bin/env python3
"""
Virtual device fleet simulator for GridWatcher v0.3.
Exercises feeder voltage correlation clustering, cold-start fallback,
post-outage retraining, sibling model distribution, and unplug quarantine.
"""

import os
import sys
import time
import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from cluster_server import LocalTestClient


def run_fleet_simulation(verbose: bool = True) -> dict:
    client = LocalTestClient()

    if verbose:
        print("--- GridWatcher v0.3 Fleet & Cluster Simulation ---")

    # 1. Calibrate Device 1 (Germiston Feeder A, resting baseline 230.5V)
    t_steps = np.arange(0, 60, 2)
    shared_feeder_wave = 0.8 * np.sin(t_steps * 0.25) - 0.4 * np.cos(t_steps * 0.12)
    trace_dev1 = [
        {"t": float(t), "v": float(230.5 + w), "f": 50.00, "jitter": 5.2}
        for t, w in zip(t_steps, shared_feeder_wave)
    ]
    r1 = client.post(
        "/api/v1/calibrate",
        json_data={
            "device_id": "GW-SIM-GERM-01",
            "name": "Germiston House 1",
            "suburb": "Germiston",
            "lat": -26.2180,
            "lon": 28.1680,
            "cell_lac": 1041,
            "cell_id": 44012,
            "trace": trace_dev1,
        },
        sign_as_device="GW-SIM-GERM-01",
    ).json()

    # 2. Calibrate Device 2 (Same Germiston feeder, 227.8V baseline, 2s clock lag)
    trace_dev2 = [
        {"t": float(t + 2.0), "v": float(227.8 + w * 0.98), "f": 50.00, "jitter": 5.4}
        for t, w in zip(t_steps, shared_feeder_wave)
    ]
    r2 = client.post(
        "/api/v1/calibrate",
        json_data={
            "device_id": "GW-SIM-GERM-02",
            "name": "Germiston House 2",
            "suburb": "Germiston",
            "lat": -26.2205,
            "lon": 28.1710,
            "cell_lac": 1041,
            "cell_id": 44012,
            "trace": trace_dev2,
        },
        sign_as_device="GW-SIM-GERM-02",
    ).json()

    # 3. Calibrate Device 3 (Kempton Park, LAC 1045, uncorrelated waveform -> cold start)
    uncorr_wave = 0.6 * np.cos(t_steps * 0.67 + 1.4)
    trace_dev3 = [
        {"t": float(t), "v": float(224.0 + w), "f": 49.99, "jitter": 6.1}
        for t, w in zip(t_steps, uncorr_wave)
    ]
    r3 = client.post(
        "/api/v1/calibrate",
        json_data={
            "device_id": "GW-SIM-KEMP-01",
            "name": "Kempton Park Unit 1",
            "suburb": "Kempton Park",
            "lat": -26.1076,
            "lon": 28.2336,
            "cell_lac": 1045,
            "cell_id": 62001,
            "trace": trace_dev3,
        },
        sign_as_device="GW-SIM-KEMP-01",
    ).json()

    if verbose:
        print(f"[1] GW-SIM-GERM-01 -> {r1['cluster_id']} (baseline {r1['learned_v_baseline']}V)")
        print(
            f"[2] GW-SIM-GERM-02 -> {r2['cluster_id']} "
            f"(mode={r2['assignment_mode']}, r={r2['correlation_r']}, baseline={r2['learned_v_baseline']}V)"
        )
        print(
            f"[3] GW-SIM-KEMP-01 -> {r3['cluster_id']} "
            f"(mode={r3['assignment_mode']}, baseline={r3['learned_v_baseline']}V)"
        )

    # 4. Precursor outage on GW-SIM-GERM-01 -> triggers cluster model retrain
    precursor_samples = []
    for i in range(45):
        t_s = float(i * 2)
        if i < 15:
            precursor_samples.append({"timestamp_s": t_s, "v_rms": 230.4, "f_hz": 50.00, "f_cycle_jitter": 5.5})
        else:
            k = i - 15
            precursor_samples.append(
                {
                    "timestamp_s": t_s,
                    "v_rms": float(230.0 - k * 0.75),
                    "f_hz": float(49.98 - k * 0.025),
                    "f_cycle_jitter": float(32.0 + k * 4.2),
                }
            )

    out_precursor = client.post(
        "/api/v1/outage-report",
        json_data={
            "device_id": "GW-SIM-GERM-01",
            "outage_timestamp_epoch": time.time() - 65.0,
            "drop_duration_ms": 420.0,
            "pre_cell_id": 44012,
            "post_cell_id": 44012,
            "pre_v_baseline": 230.5,
            "post_v_baseline": 230.4,
            "samples": precursor_samples,
        },
        sign_as_device="GW-SIM-GERM-01",
    ).json()

    # 5. Sibling GW-SIM-GERM-02 heartbeat -> receives updated cluster model
    hb_sibling = client.post(
        "/api/v1/heartbeat",
        json_data={
            "device_id": "GW-SIM-GERM-02",
            "v_rms": 227.9,
            "f_hz": 50.00,
            "f_cycle_jitter": 5.2,
            "mains_pgood_ok": True,
            "model_version": r2["model"]["model_version"] - 1,
        },
        sign_as_device="GW-SIM-GERM-02",
    ).json()

    # 6. Manual unplug on GW-SIM-KEMP-01 -> quarantined by pre-drop signature gate
    flat_unplug_samples = [
        {"timestamp_s": float(i * 2), "v_rms": 224.0, "f_hz": 50.00, "f_cycle_jitter": 4.8}
        for i in range(35)
    ]
    out_unplug = client.post(
        "/api/v1/outage-report",
        json_data={
            "device_id": "GW-SIM-KEMP-01",
            "outage_timestamp_epoch": time.time() - 1200.0,
            "drop_duration_ms": 12.0,
            "pre_cell_id": 62001,
            "post_cell_id": 62001,
            "pre_v_baseline": 224.0,
            "post_v_baseline": 224.0,
            "samples": flat_unplug_samples,
        },
        sign_as_device="GW-SIM-KEMP-01",
    ).json()

    if verbose:
        print(
            f"[4] Outage report (GW-SIM-GERM-01): {out_precursor['event']['event_type']} "
            f"| retrained={out_precursor['model_retrained']} -> v{out_precursor['active_model']['model_version']}"
        )
        print(
            f"[5] Sibling heartbeat (GW-SIM-GERM-02): update_available={hb_sibling['update_available']} "
            f"({hb_sibling.get('model', {}).get('binary_size_bytes', 0)} B)"
        )
        print(
            f"[6] Unplug report (GW-SIM-KEMP-01): {out_unplug['event']['event_type']} "
            f"| train_eligible={out_unplug['event']['train_eligible']}"
        )

    return {
        "germ1": r1,
        "germ2": r2,
        "kemp1": r3,
        "precursor_report": out_precursor,
        "sibling_heartbeat": hb_sibling,
        "unplug_report": out_unplug,
    }


if __name__ == "__main__":
    run_fleet_simulation(verbose=True)
