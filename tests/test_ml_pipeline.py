#!/usr/bin/env python3
"""
Automated test suite for GridWatcher v0.3 firmware headers, 10-feature TinyML pipeline,
event taxonomy gate, server security hardening, and live HTTP socket behavior.
"""

import os
import re
import sys
import time
import json
import shutil
import tempfile
import threading
import subprocess
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
import numpy as np
import pandas as pd

REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TRAINER_DIR = os.path.join(REPO_DIR, "windows_trainer")
if TRAINER_DIR not in sys.path:
    sys.path.insert(0, TRAINER_DIR)

import codegen
import features_gen
import ml_core
from cluster_server import (
    LocalTestClient,
    GridWatcherHTTPRequestHandler,
    compute_request_hmac,
    MAX_BODY_BYTES,
)
import sim_device


class TestGridWatcherV03Pipeline(unittest.TestCase):

    def test_1_hardware_pins_match_kicad_pcb(self):
        pins_path = os.path.join(REPO_DIR, "firmware", "pins.h")
        self.assertTrue(os.path.exists(pins_path), "firmware/pins.h must exist")
        with open(pins_path, "r", encoding="utf-8") as f:
            content = f.read()

        pin_macros = dict(re.findall(r"#define\s+(PIN_\w+)\s+(\d+)", content))
        pin_ints = {k: int(v) for k, v in pin_macros.items()}

        expected = {
            "PIN_BL0939_RX": 1,
            "PIN_BL0939_TX": 2,
            "PIN_BL0939_ZX": 3,
            "PIN_BQ24074_CHG": 4,
            "PIN_BQ24074_PGOOD": 5,
            "PIN_I2C_SDA": 6,
            "PIN_I2C_SCL": 7,
            "PIN_MAX17048_ALERT": 8,
            "PIN_SDNAND_CMD": 11,
            "PIN_SDNAND_CLK": 12,
            "PIN_SDNAND_DAT0": 13,
            "PIN_SDNAND_CS": 14,
            "PIN_MODEM_RESET": 15,
            "PIN_MODEM_PWRKEY": 16,
            "PIN_MODEM_TX_3V3": 17,
            "PIN_MODEM_RX_3V3": 18,
        }
        for name, gpio in expected.items():
            self.assertEqual(pin_ints.get(name), gpio, f"Pin mismatch for {name}")

        self.assertEqual(len(pin_ints.values()), len(set(pin_ints.values())), "Duplicate GPIO assignment detected")

    def test_2_shared_10_feature_schema_parity(self):
        codegen.generate()
        self.assertEqual(features_gen.GW_NUM_FEATURES, 10)
        self.assertEqual(
            features_gen.FEATURE_NAMES,
            [
                "v_rms",
                "v_delta_baseline",
                "f_hz",
                "f_cycle_jitter",
                "dV_dt_10s",
                "dF_dt_10s",
                "v_std_30s",
                "f_std_30s",
                "v_slope_30s",
                "f_slope_30s",
            ],
        )
        cpp_path = os.path.join(REPO_DIR, "firmware", "features_gen.h")
        with open(cpp_path, "r", encoding="utf-8") as f:
            cpp_text = f.read()
        self.assertIn(f"0x{features_gen.GW_FEATURE_HASH:08X}UL", cpp_text)

    def test_3_event_taxonomy_and_predrop_signature_gate(self):
        # Case A: Flat 230V/50Hz line followed by <20ms open-circuit unplug -> QUARANTINED_UNPLUG
        flat_df = pd.DataFrame(
            {
                "timestamp_s": np.arange(0, 60, 2, dtype=float),
                "v_rms": np.full(30, 230.0),
                "f_hz": np.full(30, 50.00),
                "f_cycle_jitter": np.full(30, 5.0),
            }
        )
        res_unplug = ml_core.classify_outage_event(flat_df, drop_duration_ms=15.0)
        self.assertEqual(res_unplug["event_type"], ml_core.EVENT_QUARANTINED_UNPLUG)
        self.assertFalse(res_unplug["train_eligible"])

        labeled_unplug = ml_core.label_outage_trace(flat_df, outage_start_ts=58.0, train_eligible=False)
        self.assertEqual(int(labeled_unplug["target_risk"].sum()) if len(labeled_unplug) > 0 else 0, 0)

        # Case B: Scheduled municipal maintenance -> SCHEDULED_MAINTENANCE
        res_maint = ml_core.classify_outage_event(
            flat_df, drop_duration_ms=18.0, scheduled_maintenance_match=True
        )
        self.assertEqual(res_maint["event_type"], ml_core.EVENT_SCHEDULED_MAINTENANCE)
        self.assertFalse(res_maint["train_eligible"])

        # Case C: Simultaneous sibling outage on flat drop -> INSTANT_FAULT
        res_fault = ml_core.classify_outage_event(
            flat_df, drop_duration_ms=18.0, sibling_co_occurrence=True
        )
        self.assertEqual(res_fault["event_type"], ml_core.EVENT_INSTANT_FAULT)
        self.assertFalse(res_fault["train_eligible"])

        # Case D: Device relocated (baseline shifted from 230V to 219.5V / new CellID) -> RELOCATED
        res_reloc = ml_core.classify_outage_event(
            flat_df,
            drop_duration_ms=15.0,
            pre_cell_id="44012",
            post_cell_id="59088",
            pre_v_baseline=230.0,
            post_v_baseline=219.5,
        )
        self.assertEqual(res_reloc["event_type"], ml_core.EVENT_RELOCATED)
        self.assertTrue(res_reloc["relocated"])

        # Case E: Real precursor feeder overload sag + ZX jitter -> PRECURSOR_OUTAGE
        t_arr = np.arange(0, 60, 2, dtype=float)
        sag_df = pd.DataFrame(
            {
                "timestamp_s": t_arr,
                "v_rms": 230.0 - 0.35 * t_arr,
                "f_hz": 50.00 - 0.012 * t_arr,
                "f_cycle_jitter": 10.0 + 2.5 * t_arr,
            }
        )
        res_prec = ml_core.classify_outage_event(sag_df, drop_duration_ms=350.0)
        self.assertEqual(res_prec["event_type"], ml_core.EVENT_PRECURSOR_OUTAGE)
        self.assertTrue(res_prec["train_eligible"])

    def test_4_signed_binary_model_and_operational_metrics(self):
        meta = ml_core.train_regional_model(cluster_id="test_unit", update_cpp_header=False)
        self.assertLess(meta["binary_size_bytes"], 2048, "Binary model payload should be compact (< 2KB)")
        self.assertGreaterEqual(meta["metrics"]["event_recall_at_20s_pct"], 90.0)
        self.assertLessEqual(meta["metrics"]["false_alarms_per_day"], 0.5)
        self.assertGreaterEqual(meta["metrics"]["pr_auc"], 0.90)

        bin_path = os.path.join(TRAINER_DIR, "models", "cluster_test_unit.bin")
        json_path = os.path.join(TRAINER_DIR, "models", "cluster_test_unit.json")
        try:
            with open(bin_path, "rb") as f:
                raw_bin = f.read()

            unpacked = ml_core.verify_and_unpack_binary_model(raw_bin)
            self.assertEqual(unpacked["n_trees"], meta["n_trees"])
            self.assertEqual(unpacked["n_nodes"], meta["n_nodes"])

            tampered = bytearray(raw_bin)
            tampered[-4] ^= 0xFF
            with self.assertRaises(ValueError):
                ml_core.verify_and_unpack_binary_model(bytes(tampered))
        finally:
            for p in (bin_path, json_path):
                if os.path.exists(p):
                    os.remove(p)

    def test_5_cybersecurity_hmac_and_admin_localhost_isolation(self):
        client = LocalTestClient()

        # 1. Unsigned POST to /api/v1/heartbeat -> 401 Unauthorized
        r_unsigned = client.post("/api/v1/heartbeat", json_data={"device_id": "GW-ZA-EKU-001"})
        self.assertEqual(r_unsigned.status_code, 401)

        # 2. Expired timestamp (>300s replay attack) -> 401 Unauthorized
        old_ts = f"{time.time() - 900.0:.3f}"
        body = json.dumps({"device_id": "GW-ZA-EKU-001", "v_rms": 230.0}).encode("utf-8")
        sig = compute_request_hmac("GW-ZA-EKU-001", old_ts, body)
        r_replay = client.post(
            "/api/v1/heartbeat",
            raw_body=body,
            headers={
                "X-Device-ID": "GW-ZA-EKU-001",
                "X-Timestamp": old_ts,
                "X-Signature": sig,
            },
        )
        self.assertEqual(r_replay.status_code, 401)

        # 3. External IP trying to access /admin or /api/v1/admin/overview -> 403 Forbidden
        r_ext_admin = client.get("/admin", client_ip="198.51.100.42")
        self.assertEqual(r_ext_admin.status_code, 403)
        r_ext_api = client.get("/api/v1/admin/overview", client_ip="198.51.100.42")
        self.assertEqual(r_ext_api.status_code, 403)

        # 4. External IP accessing public Live Grid Map -> 200 OK
        r_pub_map = client.get("/api/v1/public/map", client_ip="198.51.100.42")
        self.assertEqual(r_pub_map.status_code, 200)
        self.assertIn("devices", r_pub_map.json())

        # 5. Localhost (127.0.0.1) accessing /admin without proxy headers -> 200 OK
        r_loc_admin = client.get("/admin", client_ip="127.0.0.1")
        self.assertEqual(r_loc_admin.status_code, 200)

    def test_6_fleet_simulation_and_regional_clustering(self):
        sim_out = sim_device.run_fleet_simulation(verbose=False)
        self.assertEqual(sim_out["germ1"]["cluster_id"], sim_out["germ2"]["cluster_id"])
        self.assertGreaterEqual(sim_out["germ2"]["correlation_r"], 0.90)
        self.assertNotEqual(sim_out["germ1"]["cluster_id"], sim_out["kemp1"]["cluster_id"])
        self.assertTrue(sim_out["precursor_report"]["model_retrained"])
        self.assertTrue(sim_out["sibling_heartbeat"]["update_available"])
        self.assertEqual(
            sim_out["unplug_report"]["event"]["event_type"],
            ml_core.EVENT_QUARANTINED_UNPLUG,
        )
        self.assertFalse(sim_out["unplug_report"]["model_retrained"])

    def test_7_proxy_spoofing_payload_dos_and_path_sanitization(self):
        client = LocalTestClient(client_ip="127.0.0.1")

        # 1. Cloudflare tunnel request arriving over 127.0.0.1 with CF-Connecting-IP or CF-Ray must be blocked on /admin
        for hdr in (
            {"CF-Connecting-IP": "203.0.113.5"},
            {"CF-Ray": "89abcdef-JNB"},
            {"X-Forwarded-For": "203.0.113.5"},
            {"X-Real-IP": "203.0.113.5"},
        ):
            r_cf = client.get("/admin", headers=hdr, client_ip="127.0.0.1")
            self.assertEqual(r_cf.status_code, 403, f"Header {hdr} must be blocked from /admin")

        # 2. Oversized request body (> MAX_BODY_BYTES) -> 413 Payload Too Large
        huge_body = b"x" * (MAX_BODY_BYTES + 1024)
        r_huge = client.post("/api/v1/heartbeat", raw_body=huge_body)
        self.assertEqual(r_huge.status_code, 413)

        # 3. Header X-Device-ID mismatching payload device_id -> 401 Unauthorized
        r_mismatch = client.post(
            "/api/v1/heartbeat",
            json_data={"device_id": "GW-OTHER-999", "v_rms": 230.0},
            sign_as_device="GW-ZA-EKU-001",
        )
        self.assertEqual(r_mismatch.status_code, 401)

        # 4. Path traversal attempt in identifier sanitization
        self.assertEqual(ml_core.sanitize_identifier("../../etc/passwd"), "etcpasswd")
        self.assertEqual(ml_core.sanitize_identifier("   "), "global")

    def test_8_live_tcp_socket_server(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), GridWatcherHTTPRequestHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            base_url = f"http://127.0.0.1:{port}"

            # 1. Public map over real socket
            with urllib.request.urlopen(f"{base_url}/api/v1/public/map", timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertIn("devices", data)

            # 2. Localhost /admin over real socket -> 200
            with urllib.request.urlopen(f"{base_url}/admin", timeout=5) as resp:
                self.assertEqual(resp.status, 200)

            # 3. Tunnel request to /admin (with CF-Connecting-IP header) over real socket -> 403
            req_cf = urllib.request.Request(
                f"{base_url}/admin",
                headers={"CF-Connecting-IP": "198.51.100.77"},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req_cf, timeout=5)
            self.assertEqual(ctx.exception.code, 403)
            ctx.exception.close()

            # 4. Signed device heartbeat over real socket -> 200
            hb_body = json.dumps(
                {"device_id": "GW-ZA-EKU-001", "v_rms": 230.1, "f_hz": 50.00, "f_cycle_jitter": 5.0}
            ).encode("utf-8")
            ts_str = f"{time.time():.3f}"
            sig = compute_request_hmac("GW-ZA-EKU-001", ts_str, hb_body)
            req_hb = urllib.request.Request(
                f"{base_url}/api/v1/heartbeat",
                data=hb_body,
                headers={
                    "Content-Type": "application/json",
                    "X-Device-ID": "GW-ZA-EKU-001",
                    "X-Timestamp": ts_str,
                    "X-Signature": sig,
                },
                method="POST",
            )
            with urllib.request.urlopen(req_hb, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                hb_resp = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(hb_resp["status"], "ok")

            # 5. Post-outage payload upload -> logs CSV rows, retrains model, verifies GitHub backup & binary payload fetch
            precursor_samples = [
                {
                    "timestamp_s": float(i * 2),
                    "v_rms": float(230.0 - max(0, i - 10) * 0.8),
                    "f_hz": float(50.0 - max(0, i - 10) * 0.025),
                    "f_cycle_jitter": float(6.0 + max(0, i - 10) * 4.5),
                }
                for i in range(35)
            ]
            out_body = json.dumps(
                {
                    "device_id": "GW-ZA-EKU-001",
                    "outage_timestamp_epoch": time.time() - 70.0,
                    "drop_duration_ms": 380.0,
                    "pre_cell_id": 44012,
                    "post_cell_id": 44012,
                    "pre_v_baseline": 230.0,
                    "post_v_baseline": 230.0,
                    "samples": precursor_samples,
                }
            ).encode("utf-8")
            ts_out = f"{time.time():.3f}"
            sig_out = compute_request_hmac("GW-ZA-EKU-001", ts_out, out_body)
            req_out = urllib.request.Request(
                f"{base_url}/api/v1/outage-report",
                data=out_body,
                headers={
                    "Content-Type": "application/json",
                    "X-Device-ID": "GW-ZA-EKU-001",
                    "X-Timestamp": ts_out,
                    "X-Signature": sig_out,
                },
                method="POST",
            )
            with urllib.request.urlopen(req_out, timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                out_resp = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(out_resp["event"]["event_type"], ml_core.EVENT_PRECURSOR_OUTAGE)
                self.assertGreaterEqual(out_resp["event"]["csv_rows_logged"], 35)
                self.assertTrue(out_resp["event"]["github_sync"]["ok"])

            # 6. Live HTTP CSV Fetch (`fetch_telemetry_csv` + `load_csv_telemetry`)
            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tf_csv:
                tmp_csv_path = tf_csv.name
            try:
                fetch_res = ml_core.fetch_telemetry_csv(
                    telemetry_url=f"{base_url}/api/telemetry.csv",
                    local_csv_path=tmp_csv_path,
                )
                self.assertTrue(fetch_res["ok"])
                self.assertEqual(fetch_res["source"], "remote_http")
                self.assertGreaterEqual(fetch_res["rows"], 35)

                df_loaded = ml_core.load_csv_telemetry(tmp_csv_path, max_rows=500)
                for col in ml_core.FEATURE_NAMES:
                    self.assertIn(col, df_loaded.columns)
            finally:
                if os.path.exists(tmp_csv_path):
                    os.remove(tmp_csv_path)

            # 7. Also verify `load_csv_telemetry` on existing repo CSVs (`gridwatcher_dataset.csv` and `telemetry.csv`)
            for existing_csv in (
                os.path.join(REPO_DIR, "gridwatcher_dataset.csv"),
                os.path.join(TRAINER_DIR, "telemetry.csv"),
            ):
                if os.path.exists(existing_csv):
                    df_ex = ml_core.load_csv_telemetry(existing_csv, max_rows=200)
                    self.assertEqual(len(df_ex), 200)
                    for col in ml_core.FEATURE_NAMES:
                        self.assertIn(col, df_ex.columns)

            # 8. Raw Binary Model Payload Download (`/api/v1/model/global.bin`) & Version Endpoint (`/version.json`)
            with urllib.request.urlopen(f"{base_url}/api/v1/model/global.bin", timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                bin_bytes = resp.read()
                unpacked = ml_core.verify_and_unpack_binary_model(bin_bytes)
                self.assertGreater(unpacked["n_trees"], 0)

            with urllib.request.urlopen(f"{base_url}/version.json", timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                ver_json = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(ver_json["schema_version"], ml_core.GW_SCHEMA_VERSION)
                self.assertIn("clusters", ver_json)
        finally:
            server.shutdown()
            server.server_close()

    def test_9_cpp_firmware_headers_compile(self):
        compiler = r"C:\Users\kyler\AppData\Local\Arduino15\packages\esp32\tools\esp-x32\2601\bin\xtensa-esp-elf-g++.exe"
        if not os.path.exists(compiler):
            compiler = shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            self.skipTest("No C++ compiler found on host")

        fw_dir = os.path.join(REPO_DIR, "firmware")
        harness_code = r"""
        #include <stdint.h>
        #include <stddef.h>
        #include "pins.h"
        #include "features_gen.h"
        #include "grid_model.h"

        int test_entry() {
            float feats[GW_NUM_FEATURES] = {230.0f, 0.0f, 50.0f, 5.2f, 0.0f, 0.0f, 0.25f, 0.02f, 0.0f, 0.0f};
            DynamicEnsembleModel dyn = {};
            uint8_t dummy_bin[64] = {0};
            bool loaded = loadDynamicBinaryModel(dummy_bin, sizeof(dummy_bin), &dyn);
            float risk = predictGridRisk(feats, &dyn);
            float l2a  = evaluateLayer2AUnsupervised(feats);
            return (!loaded && risk >= 0.0f && l2a >= 0.0f && PIN_BL0939_ZX == 3 && PIN_BQ24074_PGOOD == 5) ? 0 : 1;
        }
        """
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False, encoding="utf-8") as tf:
            tf.write(harness_code)
            cpp_file = tf.name

        try:
            proc = subprocess.run(
                [compiler, "-std=gnu++17", "-fsyntax-only", f"-I{fw_dir}", cpp_file],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"C++ firmware header compile check failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}",
            )
        finally:
            if os.path.exists(cpp_file):
                os.remove(cpp_file)

    def test_10_gui_retrainer_worker_end_to_end(self):
        import gridwatcher_ml_gui

        logs = []
        outcomes = []
        worker = gridwatcher_ml_gui.RetrainerWorker(cluster_id="global", skip_git_push=True)
        worker.log_signal.connect(lambda m: logs.append(m))
        worker.finished_signal.connect(lambda ok, msg: outcomes.append((ok, msg)))
        worker.run()

        self.assertEqual(len(outcomes), 1)
        self.assertTrue(outcomes[0][0], f"RetrainerWorker failed: {outcomes[0][1]} | Logs: {logs}")
        self.assertTrue(any("CSV source:" in line for line in logs))
        self.assertTrue(any("GitHub sync" in line for line in logs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
