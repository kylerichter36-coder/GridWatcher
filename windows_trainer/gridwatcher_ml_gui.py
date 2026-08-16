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
        QLabel, QTextEdit, QProgressBar, QPushButton, QFrame, QDialog,
        QSlider, QGroupBox, QGridLayout
    )
    from PyQt5.QtCore import Qt, QThread, pyqtSignal
    from PyQt5.QtGui import QFont
except ImportError:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QTextEdit, QProgressBar, QPushButton, QFrame, QDialog,
        QSlider, QGroupBox, QGridLayout
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

MAX_APPLICATION_FLASH_BYTES = 1310720 # 1.25 MB partition limit for FireBeetle 2 ESP32-C6

class RetrainerWorker(QThread):
    progress_signal = pyqtSignal(int, str)
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, initial_trees=3, initial_depth=4, allowed_configs=None, skip_git_and_ota=False):
        super().__init__()
        self.initial_trees = initial_trees
        self.initial_depth = initial_depth
        self.allowed_configs = allowed_configs
        self.skip_git_and_ota = skip_git_and_ota

    def run(self):
        try:
            # Startup diagnostics — log all resolved paths so failures are visible
            self.log_signal.emit(f"[INIT] Script dir  : {_SCRIPT_DIR}")
            self.log_signal.emit(f"[INIT] Repo dir    : {REPO_DIR}")
            self.log_signal.emit(f"[INIT] Build dir   : {BUILD_DIR}")
            self.log_signal.emit(f"[INIT] arduino-cli : {ARDUINO_CLI}")
            self.log_signal.emit(f"[INIT] CLI exists  : {os.path.isfile(ARDUINO_CLI)}")
            self.log_signal.emit(f"[INIT] Flash Limit : {MAX_APPLICATION_FLASH_BYTES:,} bytes (1.25 MB)")
            if not os.path.isfile(ARDUINO_CLI):
                self.log_signal.emit("[ERROR] arduino-cli NOT FOUND!")
                self.log_signal.emit("[ERROR] Run install_startup.bat first — it will download everything automatically.")
                self.finished_signal.emit(False, "arduino-cli not found. Run install_startup.bat first!")
                return

            # Preserve baseline state before any file changes
            baseline_version_content = None
            if os.path.exists(VERSION_JSON_PATH):
                with open(VERSION_JSON_PATH, "r") as vf:
                    baseline_version_content = vf.read()

            baseline_header_content = None
            if os.path.exists(MODEL_HEADER_PATH):
                with open(MODEL_HEADER_PATH, "r") as hf:
                    baseline_header_content = hf.read()

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
            df["gap_mask"] = gap_mask

            # 1. 10s Rate of Change: find past sample (0 < elapsed <= 15s) minimizing |elapsed - 10s| matching ESP32 C++ exactly
            t_target = df["timestamp_dt"] - pd.Timedelta(seconds=10)
            df_prev_10s = pd.merge_asof(
                pd.DataFrame({"t_target": t_target}).reset_index(),
                df[["timestamp_dt", "voltage", "frequency"]].rename(columns={"timestamp_dt": "t_prev", "voltage": "v_prev", "frequency": "f_prev"}),
                left_on="t_target",
                right_on="t_prev",
                direction="nearest",
                tolerance=pd.Timedelta(seconds=10)
            )
            
            # Vectorized fallback to ensure candidate with 0 < elapsed <= 15s minimizing |elapsed - 10s| is selected if nearest tolerance missed
            valid_mask = []
            v_prev_vals = []
            f_prev_vals = []
            dt_10s_vals = []
            
            ts_series = df["timestamp_dt"].values
            v_series = df["voltage"].values
            f_series = df["frequency"].values
            
            for idx in range(len(df)):
                t_now = ts_series[idx]
                p_t = df_prev_10s.loc[idx, "t_prev"]
                p_v = df_prev_10s.loc[idx, "v_prev"]
                p_f = df_prev_10s.loc[idx, "f_prev"]
                
                if pd.notna(p_t) and p_t < t_now:
                    elapsed = (t_now - p_t) / np.timedelta64(1, 's')
                    if elapsed <= 15.0:
                        valid_mask.append(True)
                        v_prev_vals.append(p_v)
                        f_prev_vals.append(p_f)
                        dt_10s_vals.append(10.0 if elapsed < 1.0 else elapsed)
                        continue
                
                # Iterate backward over samples in [t - 15s, t)
                best_diff = 999999.0
                best_k = -1
                for k in range(idx - 1, -1, -1):
                    elapsed = (t_now - ts_series[k]) / np.timedelta64(1, 's')
                    if elapsed <= 0: continue
                    if elapsed > 15.0: break
                    diff = abs(elapsed - 10.0)
                    if diff < best_diff:
                        best_diff = diff
                        best_k = k
                
                if best_k != -1:
                    valid_mask.append(True)
                    v_prev_vals.append(v_series[best_k])
                    f_prev_vals.append(f_series[best_k])
                    el = (t_now - ts_series[best_k]) / np.timedelta64(1, 's')
                    dt_10s_vals.append(10.0 if el < 1.0 else el)
                else:
                    valid_mask.append(False)
                    v_prev_vals.append(0.0)
                    f_prev_vals.append(0.0)
                    dt_10s_vals.append(10.0)
            
            dt_10s_arr = np.array(dt_10s_vals)
            df["dV_dt_10s"] = np.where(valid_mask, (df["voltage"] - np.array(v_prev_vals)) / dt_10s_arr, 0.0)
            df["dF_dt_10s"] = np.where(valid_mask, (df["frequency"] - np.array(f_prev_vals)) / dt_10s_arr, 0.0)
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

            # Strict 0-30s Forward-Looking Timestamp-Based Target Labeling (Gap-Aware)
            # Label = 1 if an anomaly (V < 210V or V > 250V or F outside 49.5-50.5Hz) occurs strictly in t < t_anom <= t + 30s without crossing a >35s telemetry gap
            df["is_anomaly"] = ((df["voltage"] < 210.0) | (df["voltage"] > 250.0) | (df["frequency"] < 49.5) | (df["frequency"] > 50.5)).astype(int)
            df["is_normal_now"] = (df["voltage"] >= 210.0) & (df["voltage"] <= 250.0) & (df["frequency"] >= 49.5) & (df["frequency"] <= 50.5)

            df_anom = df[df["is_anomaly"] == 1][["timestamp_dt"]].rename(columns={"timestamp_dt": "t_anom"})
            df_next_anom = pd.merge_asof(
                df[["timestamp_dt"]].reset_index(),
                df_anom,
                left_on="timestamp_dt",
                right_on="t_anom",
                direction="forward",
                allow_exact_matches=False
            )
            dt_anom = (df_next_anom["t_anom"] - df["timestamp_dt"]).dt.total_seconds()
            
            df_gaps = df[df["gap_mask"]][["timestamp_dt"]].rename(columns={"timestamp_dt": "t_gap"})
            df_next_gap = pd.merge_asof(
                df[["timestamp_dt"]].reset_index(),
                df_gaps,
                left_on="timestamp_dt",
                right_on="t_gap",
                direction="forward",
                allow_exact_matches=False
            )
            
            has_valid_future_anomaly = (dt_anom > 0.0) & (dt_anom <= 30.0) & (
                df_next_gap["t_gap"].isna() | (df_next_gap["t_gap"] > df_next_anom["t_anom"])
            )
            df["target_risk"] = np.where(df["is_normal_now"] & has_valid_future_anomaly, 1, 0)

            # Feature columns and targets
            feature_cols = ["voltage", "frequency", "cell_signal", "dV_dt_10s", "dF_dt_10s", "v_std_30s", "f_std_30s", "v_slope_30s"]
            X = df[feature_cols]
            y = df["target_risk"]
            
            # Chronological 80/20 train/test holdout split for time-series evaluation
            split_idx = int(len(df) * 0.80)
            X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
            y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

            # Define candidate model configurations (from requested config to smaller fallbacks)
            if self.allowed_configs:
                candidate_configs = list(self.allowed_configs)
            else:
                candidate_configs = [(self.initial_trees, self.initial_depth)]
                standard_fallbacks = [
                    (3, 4),
                    (3, 3),
                    (2, 4),
                    (2, 3),
                    (2, 2),
                    (1, 4),
                    (1, 3),
                    (1, 2)
                ]
                for cfg in standard_fallbacks:
                    if cfg not in candidate_configs:
                        candidate_configs.append(cfg)

            new_version = 2
            if baseline_version_content:
                try:
                    new_version = json.loads(baseline_version_content).get("version", 1) + 1
                except:
                    new_version = 2

            build_time = time.strftime('%Y-%m-%d %H:%M:%S')

            successful_config = None
            successful_clf = None
            successful_train_acc = 0.0
            successful_test_acc = 0.0
            successful_bin_size = 0
            compiled_bin_src = None

            os.makedirs(BUILD_DIR, exist_ok=True)
            sender_ino = os.path.join(REPO_DIR, "home_sender", "home_sender.ino")

            for attempt_idx, (n_trees, max_depth) in enumerate(candidate_configs, 1):
                self.progress_signal.emit(35 + int((attempt_idx / len(candidate_configs)) * 40), f"Step 2-4/6: Trying model config #{attempt_idx} ({n_trees} trees, max_depth={max_depth})...")
                self.log_signal.emit(f"\n[ATTEMPT #{attempt_idx}] Training Random Forest Ensemble ({n_trees} trees, max_depth={max_depth})...")
                
                clf = RandomForestClassifier(n_estimators=n_trees, max_depth=max_depth, random_state=42)
                clf.fit(X_train, y_train)

                train_acc = clf.score(X_train, y_train) * 100
                test_acc  = clf.score(X_test, y_test) * 100 if len(X_test) > 0 else train_acc
                acc_str = f"Train {train_acc:.1f}% | Test {test_acc:.1f}%"
                self.log_signal.emit(f"       [EVAL] Train Acc = {train_acc:.2f}% | 80/20 Test Holdout Acc = {test_acc:.2f}%")

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
                predict_calls = "\n".join([f"    float p{i} = tree{i}(voltage, frequency, signal, dV_dt_10s, dF_dt_10s, v_std_30s, f_std_30s, v_slope_30s);" for i in range(len(clf.estimators_))])
                sum_calls = " + ".join([f"p{i}" for i in range(len(clf.estimators_))])

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
{predict_calls}
    float avgProb = ({sum_calls}) / {float(len(clf.estimators_))}f;
    return avgProb * 100.0f;
}}

#endif // GRID_MODEL_H
"""
                os.makedirs(os.path.dirname(MODEL_HEADER_PATH), exist_ok=True)
                with open(MODEL_HEADER_PATH, "w") as f:
                    f.write(header_code)

                self.log_signal.emit(f"       [BUILD] Compiling home_sender.ino with arduino-cli for config ({n_trees} trees, depth {max_depth})...")
                compile_cmd = f'"{ARDUINO_CLI}" compile --fqbn {FQBN} --output-dir "{BUILD_DIR}" "{sender_ino}"'
                
                try:
                    result = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=300, cwd=REPO_DIR, shell=True)
                except OSError as e:
                    self.log_signal.emit(f"       [ERROR] OS error running compiler: {e}")
                    continue

                src = os.path.join(BUILD_DIR, "home_sender.ino.bin")
                if result.returncode == 0 and os.path.exists(src):
                    bin_size = os.path.getsize(src)
                    pct_used = (bin_size / MAX_APPLICATION_FLASH_BYTES) * 100.0
                    self.log_signal.emit(f"       [COMPILE] Output binary size: {bin_size:,} bytes ({pct_used:.1f}% of {MAX_APPLICATION_FLASH_BYTES:,} limit)")
                    
                    if bin_size <= MAX_APPLICATION_FLASH_BYTES:
                        self.log_signal.emit(f"       [SUCCESS] Config ({n_trees} trees, depth {max_depth}) compiled cleanly and fits flash limit!")
                        successful_config = (n_trees, max_depth)
                        successful_clf = clf
                        successful_train_acc = train_acc
                        successful_test_acc = test_acc
                        successful_bin_size = bin_size
                        compiled_bin_src = src
                        break
                    else:
                        self.log_signal.emit(f"       [WARN] Config ({n_trees} trees, depth {max_depth}) exceeded flash limit ({bin_size:,} > {MAX_APPLICATION_FLASH_BYTES:,}).")
                else:
                    err_output = (result.stderr or result.stdout or "").strip()
                    last_line = err_output.splitlines()[-1] if err_output else "Unknown build failure"
                    self.log_signal.emit(f"       [WARN] Config ({n_trees} trees, depth {max_depth}) failed compilation: {last_line}")
                    if "text section exceeds available space" in err_output or "Sketch too big" in err_output:
                        self.log_signal.emit("       [FALLBACK] Reason: Application text section exceeds available flash space in board.")

            if not successful_config:
                self.log_signal.emit("\n[FAILURE] ALL ALLOWED MODEL CONFIGURATIONS FAILED TO COMPILE OR EXCEEDED FLASH LIMIT!")
                self.log_signal.emit("          Restoring baseline grid_model.h and version.json...")
                if baseline_header_content:
                    with open(MODEL_HEADER_PATH, "w") as f:
                        f.write(baseline_header_content)
                if baseline_version_content:
                    with open(VERSION_JSON_PATH, "w") as vf:
                        vf.write(baseline_version_content)
                
                self.finished_signal.emit(False, "Compilation failed for all model configs. Baseline release remains untouched.")
                return

            # Update version.json and copy home_sender.bin ONLY AFTER compilation succeeds!
            self.progress_signal.emit(75, "Step 4/6: Updating version.json & firmware binary...")
            self.log_signal.emit("[4/6] Updating version.json & finalizing home_sender.bin...")
            
            v_data = {"version": new_version, "build_time": build_time}
            with open(VERSION_JSON_PATH, "w") as vf:
                json.dump(v_data, vf, indent=2)

            dst = os.path.join(REPO_DIR, "home_sender.bin")
            import shutil
            shutil.copy(compiled_bin_src, dst)
            self.log_signal.emit(f"       [SUCCESS] Version incremented to v{new_version}. home_sender.bin updated ({successful_bin_size:,} bytes).")

            if self.skip_git_and_ota:
                self.log_signal.emit("       [TEST MODE] Skipping Git sync, Orange Pi upload, and OTA triggers.")
                self.progress_signal.emit(100, "COMPLETE: Process Finished (Test Mode).")
                self.finished_signal.emit(True, f"SUCCESS: ML Model v{v_data['version']} retrained & compiled.")
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

class MLBrainDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GridWatcher ML Brain — Real-Time Model Simulator")
        self.setFixedSize(850, 620)
        self.setStyleSheet("""
            QDialog { background-color: #0b0f19; }
            QLabel { color: #f1f5f9; font-family: 'Segoe UI', Arial, sans-serif; }
            QGroupBox { border: 1px solid #1e293b; border-radius: 8px; margin-top: 10px; font-weight: bold; color: #38bdf8; font-size: 12px; padding-top: 14px; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 6px; }
            QSlider::groove:horizontal { height: 6px; background: #1e293b; border-radius: 3px; }
            QSlider::sub-page:horizontal { background: #38bdf8; border-radius: 3px; }
            QSlider::handle:horizontal { background: #f8fafc; border: 1px solid #38bdf8; width: 16px; margin-top: -5px; margin-bottom: -5px; border-radius: 8px; }
            QPushButton.scenario_btn { background-color: #1e293b; color: #f8fafc; font-size: 11px; font-weight: 600; border-radius: 5px; padding: 6px 10px; border: 1px solid #334155; }
            QPushButton.scenario_btn:hover { background-color: #334155; border-color: #38bdf8; }
            QTextEdit { background-color: #111827; color: #a5f3fc; border: 1px solid #1e293b; border-radius: 6px; font-family: 'Consolas', monospace; font-size: 11px; padding: 8px; }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Left Column: Sliders & Controls
        left_box = QWidget()
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        # Quick Scenarios Frame
        sc_group = QGroupBox("Quick Grid Scenarios")
        sc_layout = QHBoxLayout(sc_group)
        
        btn_norm = QPushButton("1. Normal (230V)", self)
        btn_norm.setProperty("class", "scenario_btn")
        btn_norm.clicked.connect(lambda: self.load_scenario(230.2, 50.01, -95.0, 0.02, 0.01, 0.45, 0.05, 0.01))
        sc_layout.addWidget(btn_norm)

        btn_sag = QPushButton("2. Sag/Brownout (204V)", self)
        btn_sag.setProperty("class", "scenario_btn")
        btn_sag.clicked.connect(lambda: self.load_scenario(204.5, 49.62, -98.0, -0.85, -0.05, 3.42, 0.85, -0.62))
        sc_layout.addWidget(btn_sag)

        btn_jit = QPushButton("3. Jitter Storm (52.4Hz)", self)
        btn_jit.setProperty("class", "scenario_btn")
        btn_jit.clicked.connect(lambda: self.load_scenario(222.0, 52.40, -104.0, -0.10, 0.35, 1.80, 2.15, -0.05))
        sc_layout.addWidget(btn_jit)

        btn_out = QPushButton("4. Blackout (192V)", self)
        btn_out.setProperty("class", "scenario_btn")
        btn_out.clicked.connect(lambda: self.load_scenario(192.0, 48.90, -110.0, -1.80, -0.25, 4.80, 1.95, -1.20))
        sc_layout.addWidget(btn_out)

        left_layout.addWidget(sc_group)

        # Slider Group
        sl_group = QGroupBox("Live Electrical Input Signals")
        sl_layout = QGridLayout(sl_group)
        sl_layout.setSpacing(8)

        self.sliders = {}
        self.val_labels = {}

        params = [
            ("voltage",    "Voltage (V)",               1500, 2600, 2300, 10.0, "V"),
            ("frequency",  "Frequency (Hz)",            4500, 5500, 5000, 100.0, "Hz"),
            ("signal",     "Cell Signal RSRP (dBm)",    -120, -60,  -95,  1.0, "dBm"),
            ("dv",         "10s dV/dt (V/s)",           -300, 300,  0,    100.0, "V/s"),
            ("df",         "10s dF/dt (Hz/s)",          -100, 100,  0,    100.0, "Hz/s"),
            ("v_std",      "30s Volt StdDev (V)",       0,    1000, 50,   100.0, "V"),
            ("f_std",      "30s Freq StdDev (Hz)",      0,    500,  10,   100.0, "Hz"),
            ("v_slope",    "30s Volt Slope (V/s)",      -300, 300,  0,    100.0, "V/s"),
        ]

        for row, (key, title, min_v, max_v, def_v, scale, unit) in enumerate(params):
            lbl = QLabel(title)
            lbl.setFont(QFont("Segoe UI", 9))
            
            slider = QSlider(Qt.Orientation.Horizontal if hasattr(Qt, 'Orientation') else Qt.Horizontal)
            slider.setRange(min_v, max_v)
            slider.setValue(def_v)
            
            val_lbl = QLabel(f"{def_v/scale:.2f} {unit}")
            val_lbl.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            val_lbl.setStyleSheet("color: #38bdf8;")
            val_lbl.setFixedWidth(85)
            
            slider.valueChanged.connect(lambda _, k=key, s=scale, u=unit, vl=val_lbl: self.on_slider_change(k, s, u, vl))
            
            sl_layout.addWidget(lbl, row, 0)
            sl_layout.addWidget(slider, row, 1)
            sl_layout.addWidget(val_lbl, row, 2)
            
            self.sliders[key] = (slider, scale, unit)
            self.val_labels[key] = val_lbl

        left_layout.addWidget(sl_group)
        layout.addWidget(left_box, 6)

        # Right Column: Model Brain Evaluation & Trees
        right_box = QWidget()
        right_layout = QVBoxLayout(right_box)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        # Risk Gauge Header Box
        gauge_group = QGroupBox("Model Decision & Risk Gauge")
        gauge_layout = QVBoxLayout(gauge_group)
        
        self.lbl_risk_score = QLabel("0.0% RISK")
        self.lbl_risk_score.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        self.lbl_risk_score.setAlignment(Qt.AlignmentFlag.AlignCenter if hasattr(Qt, 'AlignmentFlag') else Qt.AlignCenter)
        self.lbl_risk_score.setStyleSheet("color: #4ade80;")
        gauge_layout.addWidget(self.lbl_risk_score)

        self.lbl_action = QLabel("STATUS: NORMAL (SAFE)")
        self.lbl_action.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.lbl_action.setAlignment(Qt.AlignmentFlag.AlignCenter if hasattr(Qt, 'AlignmentFlag') else Qt.AlignCenter)
        self.lbl_action.setStyleSheet("color: #94a3b8;")
        gauge_layout.addWidget(self.lbl_action)

        self.lbl_trees = QLabel("Tree 0: 0.0% | Tree 1: 0.0% | Tree 2: 0.0%")
        self.lbl_trees.setFont(QFont("Consolas", 10))
        self.lbl_trees.setAlignment(Qt.AlignmentFlag.AlignCenter if hasattr(Qt, 'AlignmentFlag') else Qt.AlignCenter)
        self.lbl_trees.setStyleSheet("color: #cbd5e1;")
        gauge_layout.addWidget(self.lbl_trees)

        right_layout.addWidget(gauge_group)

        # Decision Tree Rules Display
        rules_group = QGroupBox("Embedded C++ Tree Rules (grid_model.h)")
        rules_layout = QVBoxLayout(rules_group)
        self.txt_rules = QTextEdit()
        self.txt_rules.setReadOnly(True)
        self.load_rules_text()
        rules_layout.addWidget(self.txt_rules)
        right_layout.addWidget(rules_group)

        layout.addWidget(right_box, 5)
        self.update_simulation()

    def on_slider_change(self, key, scale, unit, val_lbl):
        slider, _, _ = self.sliders[key]
        val = slider.value() / scale
        val_lbl.setText(f"{val:.2f} {unit}")
        self.update_simulation()

    def load_scenario(self, v, f, s, dv, df, v_std, f_std, v_slope):
        vals = {"voltage": v, "frequency": f, "signal": s, "dv": dv, "df": df, "v_std": v_std, "f_std": f_std, "v_slope": v_slope}
        for k, val in vals.items():
            if k in self.sliders:
                slider, scale, unit = self.sliders[k]
                slider.blockSignals(True)
                slider.setValue(int(val * scale))
                slider.blockSignals(False)
                self.val_labels[k].setText(f"{val:.2f} {unit}")
        self.update_simulation()

    def load_rules_text(self):
        if os.path.exists(MODEL_HEADER_PATH):
            try:
                with open(MODEL_HEADER_PATH, "r", encoding="utf-8") as f:
                    self.txt_rules.setPlainText(f.read())
                return
            except:
                pass
        self.txt_rules.setPlainText("// grid_model.h not found.")

    def update_simulation(self):
        v = self.sliders["voltage"][0].value() / self.sliders["voltage"][1]
        f = self.sliders["frequency"][0].value() / self.sliders["frequency"][1]
        s = self.sliders["signal"][0].value() / self.sliders["signal"][1]
        dv = self.sliders["dv"][0].value() / self.sliders["dv"][1]
        df = self.sliders["df"][0].value() / self.sliders["df"][1]
        v_std = self.sliders["v_std"][0].value() / self.sliders["v_std"][1]
        f_std = self.sliders["f_std"][0].value() / self.sliders["f_std"][1]
        v_slope = self.sliders["v_slope"][0].value() / self.sliders["v_slope"][1]

        # Tree 0 (v33 Logic)
        if f_std <= 1.8223:
            p0 = (0.0 if f <= 49.4950 else 0.8389) if df <= 0.0776 else ((0.0678 if f <= 50.4950 else 0.8382) if v_std <= 2.8910 else (0.8841 if df <= 0.2227 else 0.0))
        else:
            p0 = (0.8523 if f_std <= 2.1158 else 0.0) if df <= -0.1983 else (0.0177 if f_std <= 2.4578 else 0.8407)

        # Tree 1
        if f_std <= 1.8223:
            p1 = (0.0 if f <= 49.4950 else 0.8389) if df <= 0.0776 else ((0.0684 if f <= 50.4950 else 0.8382) if v_std <= 2.8910 else (0.8841 if df <= 0.2227 else 0.0))
        else:
            p1 = (0.8523 if f_std <= 2.1158 else 0.0) if df <= -0.1983 else (0.0177 if f_std <= 2.4578 else 0.8407)

        # Tree 2
        if f_std <= 1.8223:
            p2 = (0.0 if f <= 49.4950 else 0.8389) if df <= 0.0776 else ((0.0684 if f <= 50.4950 else 0.8382) if v_std <= 2.8910 else (0.8841 if df <= 0.2227 else 0.0))
        else:
            p2 = (0.8523 if f_std <= 2.1158 else 0.0) if df <= -0.1983 else (0.0177 if f_std <= 2.4578 else 0.8407)

        risk = (p0 + p1 + p2) / 3.0 * 100.0
        self.lbl_trees.setText(f"Tree 0: {p0*100:.1f}% | Tree 1: {p1*100:.1f}% | Tree 2: {p2*100:.1f}%")
        self.lbl_risk_score.setText(f"{risk:.1f}% RISK")

        if risk >= 75.0 or v < 180.0:
            self.lbl_risk_score.setStyleSheet("color: #ef4444;")
            self.lbl_action.setText("ACTION: 📲 PREDICTIVE SMS ALERT TRIGGERED!")
            self.lbl_action.setStyleSheet("color: #ef4444; font-weight: bold;")
        elif risk >= 40.0:
            self.lbl_risk_score.setStyleSheet("color: #facc15;")
            self.lbl_action.setText("ACTION: ⚠️ ELEVATED RISK LOGGED")
            self.lbl_action.setStyleSheet("color: #facc15; font-weight: bold;")
        else:
            self.lbl_risk_score.setStyleSheet("color: #4ade80;")
            self.lbl_action.setText("ACTION: NORMAL (GRID STABLE)")
            self.lbl_action.setStyleSheet("color: #4ade80;")

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
            QPushButton#btn_start { background-color: #16a34a; color: #ffffff; font-weight: 600; font-size: 13px; border-radius: 6px; padding: 10px 16px; border: none; }
            QPushButton#btn_start:hover { background-color: #15803d; }
            QPushButton#btn_brain { background-color: #0284c7; color: #ffffff; font-weight: 600; font-size: 13px; border-radius: 6px; padding: 10px 16px; border: none; }
            QPushButton#btn_brain:hover { background-color: #0369a1; }
            QPushButton#btn_cancel { background-color: #dc2626; color: #ffffff; font-weight: 600; font-size: 13px; border-radius: 6px; padding: 10px 16px; border: none; }
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

        # Action Buttons Layout (Start vs View Brain vs Cancel)
        self.action_frame = QFrame(self)
        action_layout = QHBoxLayout(self.action_frame)
        action_layout.setContentsMargins(8, 8, 8, 8)
        action_layout.setSpacing(10)

        self.btn_start = QPushButton("START RETRAINING", self)
        self.btn_start.setObjectName("btn_start")
        self.btn_start.clicked.connect(self.start_pipeline)
        action_layout.addWidget(self.btn_start)

        self.btn_brain = QPushButton("VIEW ML BRAIN", self)
        self.btn_brain.setObjectName("btn_brain")
        self.btn_brain.clicked.connect(self.open_brain_viewer)
        action_layout.addWidget(self.btn_brain)

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

    def open_brain_viewer(self):
        dlg = MLBrainDialog(self)
        dlg.exec() if hasattr(dlg, 'exec') else dlg.exec_()

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
