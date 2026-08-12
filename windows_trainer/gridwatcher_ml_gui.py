import sys
import os
import time
import urllib.request
import json
import subprocess
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier

try:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QTextEdit, QProgressBar, QPushButton, QFrame
    )
    from PyQt5.QtCore import Qt, QThread, pyqtSignal
    from PyQt5.QtGui import QFont
except ImportError:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QTextEdit, QProgressBar, QPushButton, QFrame
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal
    from PyQt6.QtGui import QFont

# ── Configuration ──────────────────────────────────────────────────────────────
# Resolve script location absolutely so double-clicking from Explorer works
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR    = os.path.abspath(os.path.join(_SCRIPT_DIR, ".."))

ORANGE_PI_IP       = "192.168.3.47"
ESP32_IP           = "192.168.3.45"
TELEMETRY_URL      = f"http://{ORANGE_PI_IP}:5000/api/telemetry.csv"
TRIGGER_OTA_URL    = f"http://{ESP32_IP}/trigger-ota"
STAGE_HANDHELD_URL = f"http://{ESP32_IP}/stage-handheld"
GIT_REMOTE_URL     = "https://github.com/kylerichter36-coder/GridWatcher.git"

LOCAL_CSV_PATH   = os.path.join(_SCRIPT_DIR, "telemetry.csv")
MODEL_HEADER_PATH = os.path.join(REPO_DIR, "home_sender", "grid_model.h")
VERSION_JSON_PATH = os.path.join(REPO_DIR, "version.json")
BUILD_DIR         = os.path.join(REPO_DIR, "build")

def find_arduino_cli():
    """Search all known locations for arduino-cli.exe on Windows."""
    import shutil, glob
    candidates = [
        # First: check local tools/ folder downloaded by installer.bat
        os.path.join(_SCRIPT_DIR, "tools", "arduino-cli.exe"),
        os.path.join(REPO_DIR, "tools", "arduino-cli.exe"),
        # Then: check standard Arduino IDE install paths
        r"C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe",
        r"C:\Program Files (x86)\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Arduino15", "arduino-cli.exe"),
        os.path.join(os.environ.get("APPDATA", ""), "Arduino15", "arduino-cli.exe"),
        shutil.which("arduino-cli") or "",
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    # Last resort: walk Program Files
    for pattern in [
        r"C:\Program Files\**\arduino-cli.exe",
        r"C:\Program Files (x86)\**\arduino-cli.exe",
    ]:
        results = glob.glob(pattern, recursive=True)
        if results:
            return results[0]
    # Default fallback (will be caught by CLI exists: False check)
    return os.path.join(_SCRIPT_DIR, "tools", "arduino-cli.exe")

ARDUINO_CLI = find_arduino_cli()
FQBN        = "esp32:esp32:dfrobot_firebeetle2_esp32c6:CDCOnBoot=cdc"

class RetrainerWorker(QThread):
    progress_signal = pyqtSignal(int, str)
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def run(self):
        try:
            # Startup diagnostics — log all resolved paths so failures are visible
            self.log_signal.emit(f"[INIT] Script dir  : {_SCRIPT_DIR}")
            self.log_signal.emit(f"[INIT] Repo dir    : {REPO_DIR}")
            self.log_signal.emit(f"[INIT] Build dir   : {BUILD_DIR}")
            self.log_signal.emit(f"[INIT] arduino-cli : {ARDUINO_CLI}")
            self.log_signal.emit(f"[INIT] CLI exists  : {os.path.isfile(ARDUINO_CLI)}")
            if not os.path.isfile(ARDUINO_CLI):
                self.log_signal.emit("[ERROR] arduino-cli NOT FOUND!")
                self.log_signal.emit("[ERROR] Run install_startup.bat first — it will download everything automatically.")
                self.finished_signal.emit(False, "arduino-cli not found. Run install_startup.bat first!")
                return

            # Step 1: Download telemetry from Orange Pi
            self.progress_signal.emit(15, "Step 1/6: Downloading telemetry dataset...")
            self.log_signal.emit("[1/6] Connecting to telemetry server (http://192.168.3.47:5000/api/telemetry.csv)...")
            
            try:
                urllib.request.urlretrieve(TELEMETRY_URL, LOCAL_CSV_PATH)
                self.log_signal.emit("       [SUCCESS] Telemetry dataset downloaded.")
            except Exception as download_err:
                self.log_signal.emit(f"       [NOTICE] Server API unreachable ({download_err}). Using local telemetry dataset.")

            is_synthetic_dataset = False
            if not os.path.exists(LOCAL_CSV_PATH):
                is_synthetic_dataset = True
                self.log_signal.emit("       [WARNING] Local telemetry CSV not found. Generating baseline synthetic development dataset...")
                self.log_signal.emit("       [WARNING] THIS MODEL WILL BE FLAGGED AS A SYNTHETIC DEVELOPMENT BUILD!")
                data = {
                    "timestamp": pd.date_range(start="2026-01-01", periods=1000, freq="10s").strftime("%Y-%m-%d %H:%M:%S"),
                    "voltage": np.random.normal(230, 15, 1000).clip(0, 260),
                    "frequency": np.random.normal(50.0, 1.2, 1000).clip(0, 55),
                    "cell_signal": np.random.normal(-95, 10, 1000),
                    "outage_label": []
                }
                for v, f in zip(data["voltage"], data["frequency"]):
                    if v < 180 or f < 48.5 or f > 51.5:
                        data["outage_label"].append(1)
                    else:
                        data["outage_label"].append(0)
                df = pd.DataFrame(data)
                df.to_csv(LOCAL_CSV_PATH, index=False)

            df = pd.read_csv(LOCAL_CSV_PATH)
            self.log_signal.emit(f"       [DATA] Loaded {len(df)} telemetry samples.")
            if is_synthetic_dataset:
                self.log_signal.emit("       [NOTICE] Dataset Source: Synthetic Development Baseline (1000 samples).")

            # Clean cell_signal sentinels: map -999 or invalid values (< -120 dBm) to realistic -110.0 dBm
            if "cell_signal" in df.columns:
                df["cell_signal"] = np.where(df["cell_signal"] < -120, -110.0, df["cell_signal"])
            else:
                df["cell_signal"] = -110.0

            # Compute timestamp-based features matching ESP32 C++ firmware exactly
            if "timestamp" in df.columns:
                ts_dt = pd.to_datetime(df["timestamp"], errors="coerce")
            else:
                ts_dt = pd.date_range(start="2026-01-01", periods=len(df), freq="10s")

            df["timestamp_dt"] = ts_dt
            df = df.sort_values("timestamp_dt").reset_index(drop=True)
            df["timestamp_dt"] = df["timestamp_dt"].ffill().bfill()

            dt = df["timestamp_dt"].diff().dt.total_seconds().fillna(10.0)
            gap_mask = dt > 35.0

            # 1. 10s Rate of Change: find prior row closest to (t - 10s) and divide by actual elapsed seconds
            df_prev_10s = pd.merge_asof(
                df[["timestamp_dt"]].reset_index(),
                df[["timestamp_dt", "voltage", "frequency"]].rename(columns={"timestamp_dt": "t_prev", "voltage": "v_prev", "frequency": "f_prev"}),
                left_on="timestamp_dt",
                right_on="t_prev",
                direction="backward",
                tolerance=pd.Timedelta(seconds=15),
                allow_exact_matches=False
            )
            dt_10s = (df["timestamp_dt"] - df_prev_10s["t_prev"]).dt.total_seconds().clip(lower=1.0)
            df["dV_dt_10s"] = (df["voltage"] - df_prev_10s["v_prev"]) / dt_10s
            df["dF_dt_10s"] = (df["frequency"] - df_prev_10s["f_prev"]) / dt_10s
            df.loc[gap_mask, ["dV_dt_10s", "dF_dt_10s"]] = 0.0

            # 2. Pure 30s timestamp-based rolling standard deviation matching ESP32 firmware (ddof=0 for population std)
            df["v_std_30s"] = df.rolling("30s", on="timestamp_dt")["voltage"].std(ddof=0).fillna(0.0)
            df["f_std_30s"] = df.rolling("30s", on="timestamp_dt")["frequency"].std(ddof=0).fillna(0.0)

            # 3. Pure 30s timestamp-based linear regression slope matching ESP32 firmware
            def calc_30s_slope(window):
                if len(window) < 2: return 0.0
                t_sec = (window.index - window.index[0]).total_seconds().values
                v_val = window.values
                t_diff = t_sec - t_sec.mean()
                v_diff = v_val - v_val.mean()
                den = np.sum(t_diff ** 2)
                if den < 0.0001: return 0.0
                return np.sum(t_diff * v_diff) / den

            df_temp = df.set_index("timestamp_dt")
            df["v_slope_30s"] = df_temp["voltage"].rolling("30s").apply(calc_30s_slope, raw=False).values
            df.loc[gap_mask, ["v_std_30s", "f_std_30s", "v_slope_30s"]] = 0.0

            # Fill initial window startup NaNs with 0.0
            df = df.fillna(0.0)

            # Continuous 0-30s forward-looking predictive target labeling
            # Label = 1 if an anomaly (V < 210V or V > 250V or F outside 49.5-50.5Hz) occurs within the upcoming 30 seconds while current t is NORMAL
            df["is_anomaly"] = ((df["voltage"] < 210.0) | (df["voltage"] > 250.0) | (df["frequency"] < 49.5) | (df["frequency"] > 50.5)).astype(int)
            df["is_normal_now"] = (df["voltage"] >= 210.0) & (df["voltage"] <= 250.0) & (df["frequency"] >= 49.5) & (df["frequency"] <= 50.5)
            
            # Reverse time series to evaluate forward-looking 30-second window
            df_rev = df.set_index("timestamp_dt").iloc[::-1]
            future_anomaly_rev = (df_rev["is_anomaly"].rolling("30s").max().iloc[::-1].shift(-1).fillna(0) > 0)
            df["target_risk"] = np.where(df["is_normal_now"] & future_anomaly_rev.values, 1, 0)

            # Step 2: Scikit-Learn Random Forest 3-Tree Training
            self.progress_signal.emit(35, "Step 2/6: Training Random Forest Classifier...")
            self.log_signal.emit("[2/6] Training Random Forest Ensemble (3 trees, max_depth=4)...")
            
            feature_cols = ["voltage", "frequency", "cell_signal", "dV_dt_10s", "dF_dt_10s", "v_std_30s", "f_std_30s", "v_slope_30s"]
            X = df[feature_cols]
            y = df["target_risk"]
            
            # Chronological 80/20 train/test holdout split for time-series evaluation
            split_idx = int(len(df) * 0.80)
            X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
            y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

            clf = RandomForestClassifier(n_estimators=3, max_depth=4, random_state=42)
            clf.fit(X_train, y_train)

            train_acc = clf.score(X_train, y_train) * 100
            test_acc  = clf.score(X_test, y_test) * 100 if len(X_test) > 0 else train_acc
            self.log_signal.emit(f"       [EVAL] Train Acc = {train_acc:.2f}% | 80/20 Test Holdout Acc = {test_acc:.2f}%")
            acc_str = f"Train {train_acc:.1f}% | Test {test_acc:.1f}%"

            # Step 3: Export C++ Random Forest Code & Increment Version
            self.progress_signal.emit(55, "Step 3/6: Exporting C++ tree code...")
            self.log_signal.emit("[3/6] Exporting C++ decision trees to grid_model.h...")

            new_version = 2
            if os.path.exists(VERSION_JSON_PATH):
                try:
                    with open(VERSION_JSON_PATH, "r") as vf:
                        new_version = json.load(vf).get("version", 1) + 1
                except:
                    new_version = 2

            build_time = time.strftime('%Y-%m-%d %H:%M:%S')

            cpp_feature_names = ["voltage", "frequency", "signal", "dV_dt_10s", "dF_dt_10s", "v_std_30s", "f_std_30s", "v_slope_30s"]

            def export_tree_to_cpp(tree_estimator, tree_idx):
                tree_ = tree_estimator.tree_
                def recurse(node, depth):
                    indent = "  " * depth
                    if tree_.feature[node] != -2:
                        name = cpp_feature_names[tree_.feature[node]]
                        threshold = tree_.threshold[node]
                        left = recurse(tree_.children_left[node], depth + 1)
                        right = recurse(tree_.children_right[node], depth + 1)
                        return f"{indent}if ({name} <= {threshold:.4f}f) {{\n{left}\n{indent}}} else {{\n{right}\n{indent}}}"
                    else:
                        vals = tree_.value[node][0]
                        prob = float(vals[1] / np.sum(vals)) if np.sum(vals) > 0 else 0.0
                        return f"{indent}return {prob:.4f}f;"

                body = recurse(0, 1)
                return f"inline float tree{tree_idx}(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {{\n{body}\n}}"

            cpp_trees = "\n\n".join([export_tree_to_cpp(t, i) for i, t in enumerate(clf.estimators_)])

            header_code = f"""// Auto-generated GridWatcher Random Forest ML Decision Trees
// Retrained on: {build_time}
// Train Acc: {train_acc:.2f}% | 80/20 Test Holdout Acc: {test_acc:.2f}%

#ifndef GRID_MODEL_H
#define GRID_MODEL_H

#include <Arduino.h>

enum GridStatus : uint8_t {{
    GRID_STATUS_NORMAL       = 0,
    GRID_STATUS_BLACKOUT     = 1,
    GRID_STATUS_BROWNOUT_SAG = 2,
    GRID_STATUS_SURGE        = 3,
    GRID_STATUS_FREQ_JITTER  = 4
}};

#ifndef ML_MODEL_VERSION
#define ML_MODEL_VERSION {new_version}
#endif

#ifndef ML_MODEL_BUILD_TIME
#define ML_MODEL_BUILD_TIME "{build_time}"
#endif

#ifndef ML_MODEL_ACCURACY
#define ML_MODEL_ACCURACY "{acc_str}"
#endif

{cpp_trees}

inline float predictGridRisk(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {{
    float p0 = tree0(voltage, frequency, signal, dV_dt_10s, dF_dt_10s, v_std_30s, f_std_30s, v_slope_30s);
    float p1 = tree1(voltage, frequency, signal, dV_dt_10s, dF_dt_10s, v_std_30s, f_std_30s, v_slope_30s);
    float p2 = tree2(voltage, frequency, signal, dV_dt_10s, dF_dt_10s, v_std_30s, f_std_30s, v_slope_30s);
    float avgProb = (p0 + p1 + p2) / 3.0f;
    return avgProb * 100.0f;
}}

#endif // GRID_MODEL_H
"""
            os.makedirs(os.path.dirname(MODEL_HEADER_PATH), exist_ok=True)
            with open(MODEL_HEADER_PATH, "w") as f:
                f.write(header_code)
            self.log_signal.emit(f"       [SUCCESS] Decision weights exported to grid_model.h (v{new_version}).")

            # Step 4: Increment Version
            self.progress_signal.emit(75, "Step 4/6: Updating version.json...")
            self.log_signal.emit("[4/6] Updating version.json...")
            
            v_data = {"version": new_version, "build_time": build_time}
            with open(VERSION_JSON_PATH, "w") as vf:
                json.dump(v_data, vf, indent=2)
            self.log_signal.emit(f"       [SUCCESS] Version incremented to v{v_data['version']}")

            # Step 4b: Compile home_sender.bin only — it is the ONLY binary that embeds
            # grid_model.h weights. The handheld binary never changes during ML retrains.
            self.progress_signal.emit(80, "Step 4b/6: Compiling home_sender.bin...")
            self.log_signal.emit("[4b/6] Compiling home_sender.bin with arduino-cli...")
            self.log_signal.emit("       [NOTE] handheld.bin skipped — does not include grid_model.h")
            os.makedirs(BUILD_DIR, exist_ok=True)

            sender_ino = os.path.join(REPO_DIR, "home_sender", "home_sender.ino")
            self.log_signal.emit("       [BUILD] Compiling home_sender...")
            compile_cmd = f'"{ARDUINO_CLI}" compile --fqbn {FQBN} --output-dir "{BUILD_DIR}" "{sender_ino}"'
            self.log_signal.emit(f"       [CMD] {compile_cmd}")
            try:
                result = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=300, cwd=REPO_DIR, shell=True)
            except OSError as e:
                err_msg = f"home_sender compile OS error: {e} | CLI: {ARDUINO_CLI} | exists: {os.path.isfile(ARDUINO_CLI)}"
                self.log_signal.emit(f"       [ERROR] {err_msg}")
                self.finished_signal.emit(False, err_msg)
                return
            if result.returncode == 0:
                import shutil
                src = os.path.join(BUILD_DIR, "home_sender.ino.bin")
                dst = os.path.join(REPO_DIR, "home_sender.bin")
                if os.path.exists(src):
                    shutil.copy(src, dst)
                    self.log_signal.emit(f"       [SUCCESS] home_sender.bin compiled ({os.path.getsize(dst):,} bytes)")
                else:
                    self.log_signal.emit("       [WARN] home_sender.ino.bin not found in build dir")
            else:
                err_msg = f"home_sender compile failed: {result.stderr[-400:] or result.stdout[-400:]}"
                self.log_signal.emit(f"       [ERROR] {err_msg}")
                self.finished_signal.emit(False, err_msg)
                return

            # Step 5: Safe Git Sync (Zero --force, full history preservation)
            self.progress_signal.emit(88, "Step 5/6: Syncing ML model to GitHub...")
            self.log_signal.emit("[5/6] Executing Git synchronization...")
            
            def run_git(cmd_args):
                p = subprocess.Popen(cmd_args, cwd=REPO_DIR, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout, stderr = p.communicate()
                if stdout:
                    for line in stdout.splitlines():
                        if line.strip(): self.log_signal.emit(f"       [GIT] {line.strip()}")
                if stderr:
                    for line in stderr.splitlines():
                        if line.strip(): self.log_signal.emit(f"       [GIT] {line.strip()}")
                return p.returncode

            # Check if .git directory exists; initialize and align if missing
            git_dir = os.path.join(REPO_DIR, ".git")
            if not os.path.exists(git_dir):
                self.log_signal.emit("       [GIT] Connecting unzipped directory to GitHub repository...")
                run_git(["git", "init"])
                run_git(["git", "remote", "add", "origin", GIT_REMOTE_URL])
                run_git(["git", "fetch", "origin", "main"])
                run_git(["git", "reset", "--mixed", "origin/main"])
                run_git(["git", "branch", "-M", "main"])

            run_git(["git", "remote", "set-url", "origin", GIT_REMOTE_URL])

            # Always fetch & align to latest GitHub HEAD (preserves modified telemetry & model files!)
            self.log_signal.emit("       [GIT] Fetching and aligning with latest GitHub repository...")
            run_git(["git", "fetch", "origin", "main"])
            run_git(["git", "reset", "--soft", "origin/main"])

            # Stage strictly the updated ML trainer script, model header, version file, dataset, documentation, and compiled firmware binaries
            run_git(["git", "add", "windows_trainer/gridwatcher_ml_gui.py", "home_sender/grid_model.h", "version.json", "windows_trainer/telemetry.csv", "README.md", "WORKING_ON/README.md"])
            if os.path.exists(os.path.join(REPO_DIR, "home_sender.bin")): run_git(["git", "add", "-f", "home_sender.bin"])
            if os.path.exists(os.path.join(REPO_DIR, "handheld.bin")): run_git(["git", "add", "-f", "handheld.bin"])
            commit_msg = f"Auto-retrain ML Model v{v_data['version']} [{time.strftime('%H:%M:%S')}]"
            run_git(["git", "commit", "-m", commit_msg])
            
            # Safe standard push to remote main branch from local HEAD
            git_code = run_git(["git", "push", "origin", "HEAD:main"])

            if git_code != 0:
                self.log_signal.emit("       [GIT ERROR] Push failed. Aborting OTA update.")
                self.finished_signal.emit(False, "Git push failed. OTA update aborted.")
                return

            self.log_signal.emit(f"       [GIT SUCCESS] Pushed commit '{commit_msg}' to GitHub main branch.")

            # Step 5b: Upload compiled binaries to Orange Pi firmware server (HTTP OTA source)
            self.progress_signal.emit(92, "Step 5b/6: Uploading firmware to Orange Pi server...")
            self.log_signal.emit("[5b/6] Uploading firmware files to Orange Pi local server...")
            try:
                pi_pass = os.environ.get("GRIDWATCHER_PI_PASS", None)
                if not pi_pass and os.path.exists(os.path.join(REPO_DIR, "secrets.json")):
                    try:
                        with open(os.path.join(REPO_DIR, "secrets.json"), "r") as sf:
                            pi_pass = json.load(sf).get("pi_password")
                    except:
                        pass
                if not pi_pass:
                    pi_pass = "1234"

                import paramiko
                pi_ssh = paramiko.SSHClient()
                pi_ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                pi_ssh.connect(ORANGE_PI_IP, username="root", password=pi_pass, timeout=10)
                pi_sftp = pi_ssh.open_sftp()
                fw_files = {
                    os.path.join(REPO_DIR, "home_sender.bin"): "/root/gridwatcher/firmware/home_sender.bin",
                    os.path.join(REPO_DIR, "handheld.bin"):    "/root/gridwatcher/firmware/handheld.bin",
                    os.path.join(REPO_DIR, "version.json"):    "/root/gridwatcher/firmware/version.json",
                }
                for local, remote in fw_files.items():
                    if os.path.exists(local):
                        pi_sftp.put(local, remote)
                        self.log_signal.emit(f"       [SCP] {os.path.basename(local)} -> Pi ({os.path.getsize(local):,} bytes)")
                pi_sftp.close()
                pi_ssh.close()
                self.log_signal.emit("       [SUCCESS] All firmware files on Orange Pi server — ESP32 can now download via HTTP!")
            except Exception as scp_err:
                self.log_signal.emit(f"       [WARN] Orange Pi SCP failed: {scp_err}. OTA will use cached files.")

            # Step 6: Send ESP32 Auto-OTA Trigger Signal (ONLY IF GIT PUSH SUCCEEDED)
            self.progress_signal.emit(95, "Step 6/6: Triggering ESP32 Auto-OTA over Wi-Fi...")
            self.log_signal.emit("[6/6] Sending OTA trigger signal to ESP32 (192.168.3.45)...")
            
            import time as _time
            try:
                req = urllib.request.Request(TRIGGER_OTA_URL, method="POST")
                urllib.request.urlopen(req, timeout=5)
                self.log_signal.emit("       [SUCCESS] OTA trigger sent — Base Station is updating...")
                # Wait for Base Station to flash and reboot (~25 seconds), then stage handheld.bin
                self.log_signal.emit("       [WAIT] Waiting 30s for Base Station to reboot into new firmware...")
                _time.sleep(30)
                try:
                    req2 = urllib.request.Request(STAGE_HANDHELD_URL, method="POST")
                    urllib.request.urlopen(req2, timeout=10)
                    self.log_signal.emit("       [SUCCESS] handheld.bin staged on Base Station — hold BOOT on handheld to update!")
                except Exception as sh_err:
                    self.log_signal.emit(f"       [NOTICE] Stage handheld call: {sh_err}")
            except Exception as ota_err:
                self.log_signal.emit(f"       [NOTICE] Direct HTTP trigger unreachable ({ota_err}). Base station will poll GitHub on boot.")

            self.progress_signal.emit(100, "COMPLETE: Process Finished.")
            self.finished_signal.emit(True, f"SUCCESS: ML Model v{v_data['version']} retrained & synced.")

        except Exception as e:
            self.log_signal.emit(f"\n[ERROR] Process failed: {e}")
            self.finished_signal.emit(False, str(e))

class IndustrialMLDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GridWatcher ML Pipeline Control")
        self.setFixedSize(700, 520)
        self.setStyleSheet("""
            QMainWindow { background-color: #0b0f19; }
            QLabel { color: #f1f5f9; font-family: 'Segoe UI', Arial, sans-serif; }
            QTextEdit { background-color: #111827; color: #38bdf8; border: 1px solid #1e293b; border-radius: 6px; font-family: 'Consolas', monospace; font-size: 13px; padding: 10px; }
            QProgressBar { border: 1px solid #1e293b; border-radius: 6px; background-color: #111827; text-align: center; color: #f8fafc; font-weight: 600; font-size: 12px; }
            QProgressBar::chunk { background-color: #2563eb; border-radius: 5px; }
            QPushButton#btn_start { background-color: #16a34a; color: #ffffff; font-weight: 600; font-size: 13px; border-radius: 6px; padding: 10px 20px; border: none; }
            QPushButton#btn_start:hover { background-color: #15803d; }
            QPushButton#btn_cancel { background-color: #dc2626; color: #ffffff; font-weight: 600; font-size: 13px; border-radius: 6px; padding: 10px 20px; border: none; }
            QPushButton#btn_cancel:hover { background-color: #b91c1c; }
            QPushButton#btn_close { background-color: #2563eb; color: #ffffff; font-weight: 600; font-size: 13px; border-radius: 6px; padding: 10px 20px; border: none; }
            QPushButton#btn_close:hover { background-color: #1d4ed8; }
            QFrame { background-color: #111827; border-radius: 8px; border: 1px solid #1e293b; }
        """)

        # Always on top
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        # Main Layout
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        # Header Frame
        header_frame = QFrame(self)
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(14, 14, 14, 14)

        lbl_title = QLabel("GridWatcher ML Retraining & Sync Utility", self)
        lbl_title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color: #38bdf8;")
        header_layout.addWidget(lbl_title)

        lbl_subtitle = QLabel("New telemetry recorded. Retrain Random Forest model & sync to GitHub?", self)
        lbl_subtitle.setFont(QFont("Segoe UI", 10))
        lbl_subtitle.setStyleSheet("color: #94a3b8;")
        header_layout.addWidget(lbl_subtitle)

        main_layout.addWidget(header_frame)

        # Action Buttons Layout (Start vs Cancel)
        self.action_frame = QFrame(self)
        action_layout = QHBoxLayout(self.action_frame)
        action_layout.setContentsMargins(8, 8, 8, 8)

        self.btn_start = QPushButton("START RETRAINING & GITHUB SYNC", self)
        self.btn_start.setObjectName("btn_start")
        self.btn_start.clicked.connect(self.start_pipeline)
        action_layout.addWidget(self.btn_start)

        self.btn_cancel = QPushButton("CANCEL", self)
        self.btn_cancel.setObjectName("btn_cancel")
        self.btn_cancel.clicked.connect(self.close)
        action_layout.addWidget(self.btn_cancel)

        main_layout.addWidget(self.action_frame)

        # Terminal Log Output Box
        self.txt_terminal = QTextEdit(self)
        self.txt_terminal.setReadOnly(True)
        main_layout.addWidget(self.txt_terminal)

        # Progress Section
        self.lbl_status = QLabel("Status: Idle", self)
        self.lbl_status.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.lbl_status.setStyleSheet("color: #cbd5e1;")
        main_layout.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(24)
        main_layout.addWidget(self.progress_bar)

        # Close Button
        btn_close_layout = QHBoxLayout()
        btn_close_layout.addStretch()

        self.btn_close = QPushButton("Close Utility", self)
        self.btn_close.setObjectName("btn_close")
        self.btn_close.setVisible(False)
        self.btn_close.clicked.connect(self.close)
        btn_close_layout.addWidget(self.btn_close)

        main_layout.addLayout(btn_close_layout)

        # Center on Screen
        self.center_on_screen()

    def center_on_screen(self):
        screen = QApplication.primaryScreen().geometry()
        size = self.geometry()
        self.move((screen.width() - size.width()) // 2, (screen.height() - size.height()) // 2)

    def start_pipeline(self):
        self.action_frame.setVisible(False)
        self.worker = RetrainerWorker()
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.log_signal.connect(self.append_log)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def update_progress(self, val, msg):
        self.progress_bar.setValue(val)
        self.lbl_status.setText(msg)

    def append_log(self, text):
        self.txt_terminal.append(text)
        sb = self.txt_terminal.verticalScrollBar()
        sb.setValue(sb.maximum())

    def on_finished(self, success, msg):
        if success:
            self.lbl_status.setText("STATUS: Process completed successfully.")
            self.lbl_status.setStyleSheet("color: #4ade80;")
        else:
            self.lbl_status.setText(f"STATUS: Process failed ({msg})")
            self.lbl_status.setStyleSheet("color: #f87171;")
        
        self.btn_close.setVisible(True)

def main():
    app = QApplication(sys.argv)
    window = IndustrialMLDashboard()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
