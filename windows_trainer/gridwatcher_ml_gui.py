#!/usr/bin/env python3
"""
PyQt desktop trainer and 10-feature interactive model simulator for GridWatcher v0.3.
"""

import os
import sys
import time
import webbrowser

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import ml_core
from simulate_ml_brain import simulate_prediction_10, HEADER_PATH

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


class RetrainerWorker(QThread):
    progress_signal = pyqtSignal(int, str)
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, cluster_id: str = "global", skip_git_push: bool = False):
        super().__init__()
        self.cluster_id = cluster_id
        self.skip_git_push = skip_git_push

    def run(self):
        try:
            self.progress_signal.emit(15, "Step 1/5: Fetching telemetry CSV dataset...")
            fetch_res = ml_core.fetch_telemetry_csv()
            self.log_signal.emit(
                f"[1/5] CSV source: {fetch_res['source']} ({fetch_res['path']}, ~{fetch_res['rows']} rows)"
            )
            df_csv = ml_core.load_csv_telemetry(fetch_res["path"], max_rows=600)
            df_sa = ml_core.generate_realistic_sa_dataset(seed=int(time.time()) % 1000)
            import pandas as pd
            df = pd.concat([df_sa, df_csv], ignore_index=True)
            self.log_signal.emit(f"      Prepared {len(df)} total 10-feature training samples.")

            self.progress_signal.emit(45, "Step 2/5: Training flat-node tree ensemble...")
            self.log_signal.emit("[2/5] Training candidate ensembles...")
            meta = ml_core.train_regional_model(
                df_train_raw=df,
                cluster_id=self.cluster_id,
                update_cpp_header=True,
            )

            self.progress_signal.emit(75, "Step 3/5: Signing binary payload & writing grid_model.h...")
            m = meta["metrics"]
            self.log_signal.emit(
                f"[3/5] Exported model v{meta['model_version']}: {meta['n_trees']} trees, "
                f"{meta['n_nodes']} nodes, {meta['binary_size_bytes']} B signed binary."
            )
            self.log_signal.emit(
                f"      Event Recall @ >=20s : {m['event_recall_at_20s_pct']:.1f}%\n"
                f"      Mean Lead Time       : {m['mean_lead_time_s']:.1f}s\n"
                f"      False Alarms / Day   : {m['false_alarms_per_day']:.2f}\n"
                f"      PR-AUC               : {m['pr_auc']:.4f}"
            )

            self.progress_signal.emit(90, "Step 4/5: Syncing model backup with GitHub...")
            git_res = ml_core.sync_model_to_github(
                model_version=meta["model_version"],
                cluster_id=self.cluster_id,
                push_remote=(not self.skip_git_push),
            )
            self.log_signal.emit(
                f"[4/5] GitHub sync ({git_res.get('mode')}): staged={len(git_res.get('staged_files', []))} files, ok={git_res.get('ok')}"
            )

            self.progress_signal.emit(100, "Complete: model retrained, signed, and synced.")
            self.finished_signal.emit(
                True,
                f"Model v{meta['model_version']} ready ({meta['binary_size_bytes']} B, Recall@20s={m['event_recall_at_20s_pct']:.1f}%)",
            )
        except Exception as e:
            self.log_signal.emit(f"[ERROR] {e}")
            self.finished_signal.emit(False, str(e))


class MLBrainDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GridWatcher v0.3 - 10-Feature Model Simulator")
        self.setFixedSize(920, 660)
        self.setStyleSheet("""
            QDialog { background-color: #0b0f19; }
            QLabel { color: #f1f5f9; font-family: 'Segoe UI', Arial, sans-serif; }
            QGroupBox { border: 1px solid #1e293b; border-radius: 8px; margin-top: 10px; font-weight: bold; color: #38bdf8; font-size: 12px; padding-top: 14px; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 6px; }
            QPushButton.scenario_btn { background-color: #1e293b; color: #f8fafc; font-size: 11px; font-weight: 600; border-radius: 5px; padding: 6px 10px; border: 1px solid #334155; }
            QPushButton.scenario_btn:hover { background-color: #334155; border-color: #38bdf8; }
            QTextEdit { background-color: #111827; color: #a5f3fc; border: 1px solid #1e293b; border-radius: 6px; font-family: 'Consolas', monospace; font-size: 11px; padding: 8px; }
        """)

        layout = QHBoxLayout(self)
        left_box = QWidget()
        left_layout = QVBoxLayout(left_box)

        sc_group = QGroupBox("Grid Scenarios")
        sc_layout = QHBoxLayout(sc_group)

        scenarios = [
            ("1. Normal (230V)", (230.2, 0.2, 50.01, 5.2, 0.01, 0.00, 0.30, 0.02, 0.00, 0.00)),
            ("2. Kettle Inrush (Safe)", (224.8, -5.2, 49.99, 7.5, -0.02, 0.00, 0.45, 0.02, -0.01, 0.00)),
            ("3. Feeder Sag (35s Warn)", (212.5, -17.5, 49.52, 84.0, -0.65, -0.02, 3.20, 0.19, -0.48, -0.02)),
            ("4. Collapse (20s Warn)", (198.0, -32.0, 49.12, 148.0, -1.35, -0.04, 5.10, 0.38, -0.82, -0.03)),
        ]
        for label, vals in scenarios:
            btn = QPushButton(label, self)
            btn.setProperty("class", "scenario_btn")
            btn.clicked.connect(lambda _, v=vals: self.load_scenario(*v))
            sc_layout.addWidget(btn)

        left_layout.addWidget(sc_group)

        sl_group = QGroupBox("10-Feature Input Vector (common/features.yaml)")
        sl_layout = QGridLayout(sl_group)
        self.sliders = {}
        self.val_labels = {}

        params = [
            ("v_rms",            "0. AC Voltage RMS (V)",       1500, 2600, 2300, 10.0,  "V"),
            ("v_delta_baseline", "1. Delta vs Baseline (V)",    -400,  400,    0, 10.0,  "V"),
            ("f_hz",             "2. Line Frequency (Hz)",      4500, 5500, 5000, 100.0, "Hz"),
            ("f_cycle_jitter",   "3. ZX Cycle Jitter (mHz)",       0, 2500,   52, 10.0,  "mHz"),
            ("dV_dt_10s",        "4. 10s dV/dt (V/s)",          -300,  300,    0, 100.0, "V/s"),
            ("dF_dt_10s",        "5. 10s dF/dt (Hz/s)",         -100,  100,    0, 100.0, "Hz/s"),
            ("v_std_30s",        "6. 30s Voltage StdDev (V)",      0, 1000,   30, 100.0, "V"),
            ("f_std_30s",        "7. 30s Freq StdDev (Hz)",        0,  500,    2, 100.0, "Hz"),
            ("v_slope_30s",      "8. 30s Voltage Slope (V/s)",  -300,  300,    0, 100.0, "V/s"),
            ("f_slope_30s",      "9. 30s Freq Slope (Hz/s)",    -100,  100,    0, 100.0, "Hz/s"),
        ]

        for row, (key, title, min_v, max_v, def_v, scale, unit) in enumerate(params):
            lbl = QLabel(title)
            slider = QSlider(Qt.Orientation.Horizontal if hasattr(Qt, "Orientation") else Qt.Horizontal)
            slider.setRange(min_v, max_v)
            slider.setValue(def_v)
            val_lbl = QLabel(f"{def_v/scale:.2f} {unit}")
            val_lbl.setFixedWidth(95)
            slider.valueChanged.connect(lambda _, k=key, s=scale, u=unit, vl=val_lbl: self.on_slider_change(k, s, u, vl))
            sl_layout.addWidget(lbl, row, 0)
            sl_layout.addWidget(slider, row, 1)
            sl_layout.addWidget(val_lbl, row, 2)
            self.sliders[key] = (slider, scale, unit)
            self.val_labels[key] = val_lbl

        left_layout.addWidget(sl_group)
        layout.addWidget(left_box, 6)

        right_box = QWidget()
        right_layout = QVBoxLayout(right_box)
        gauge_group = QGroupBox("Dual-Layer Risk Output")
        gauge_layout = QVBoxLayout(gauge_group)

        self.lbl_risk_score = QLabel("0.0% RISK")
        self.lbl_risk_score.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        self.lbl_risk_score.setAlignment(Qt.AlignmentFlag.AlignCenter if hasattr(Qt, "AlignmentFlag") else Qt.AlignCenter)
        gauge_layout.addWidget(self.lbl_risk_score)

        self.lbl_action = QLabel("STATUS: NORMAL")
        self.lbl_action.setAlignment(Qt.AlignmentFlag.AlignCenter if hasattr(Qt, "AlignmentFlag") else Qt.AlignCenter)
        gauge_layout.addWidget(self.lbl_action)

        self.lbl_trees = QLabel("Layer 2A: 0.0% | Layer 2B: 0.0%")
        self.lbl_trees.setAlignment(Qt.AlignmentFlag.AlignCenter if hasattr(Qt, "AlignmentFlag") else Qt.AlignCenter)
        gauge_layout.addWidget(self.lbl_trees)
        right_layout.addWidget(gauge_group)

        rules_group = QGroupBox("Exported Header (firmware/grid_model.h)")
        rules_layout = QVBoxLayout(rules_group)
        self.txt_rules = QTextEdit()
        self.txt_rules.setReadOnly(True)
        if os.path.exists(HEADER_PATH):
            with open(HEADER_PATH, "r", encoding="utf-8") as f:
                self.txt_rules.setPlainText(f.read())
        rules_layout.addWidget(self.txt_rules)
        right_layout.addWidget(rules_group)

        layout.addWidget(right_box, 5)
        self.update_simulation()

    def on_slider_change(self, key, scale, unit, val_lbl):
        slider, _, _ = self.sliders[key]
        val_lbl.setText(f"{slider.value() / scale:.2f} {unit}")
        self.update_simulation()

    def load_scenario(self, v_rms, v_delta, f_hz, jitter, dv, df, v_std, f_std, v_slope, f_slope):
        vals = {
            "v_rms": v_rms,
            "v_delta_baseline": v_delta,
            "f_hz": f_hz,
            "f_cycle_jitter": jitter,
            "dV_dt_10s": dv,
            "dF_dt_10s": df,
            "v_std_30s": v_std,
            "f_std_30s": f_std,
            "v_slope_30s": v_slope,
            "f_slope_30s": f_slope,
        }
        for k, val in vals.items():
            slider, scale, unit = self.sliders[k]
            slider.blockSignals(True)
            slider.setValue(int(val * scale))
            slider.blockSignals(False)
            self.val_labels[k].setText(f"{val:.2f} {unit}")
        self.update_simulation()

    def update_simulation(self):
        vals = [self.sliders[k][0].value() / self.sliders[k][1] for k in ml_core.FEATURE_NAMES]
        risk, l2a, l2b, _ = simulate_prediction_10(*vals)
        self.lbl_trees.setText(f"Layer 2A (Z-score): {l2a:.1f}% | Layer 2B (Forest): {l2b:.1f}%")
        self.lbl_risk_score.setText(f"{risk:.1f}% RISK")

        if risk >= 70.0 or vals[0] < 100.0:
            self.lbl_risk_score.setStyleSheet("color: #ef4444;")
            self.lbl_action.setText("ACTION: 4G SMS PRE-OUTAGE ALERT")
        elif risk >= 40.0:
            self.lbl_risk_score.setStyleSheet("color: #facc15;")
            self.lbl_action.setText("ACTION: ELEVATED INSTABILITY RISK")
        else:
            self.lbl_risk_score.setStyleSheet("color: #4ade80;")
            self.lbl_action.setText("ACTION: NORMAL (GRID STABLE)")


class IndustrialMLDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GridWatcher v0.3 - TinyML Control Center")
        self.setFixedSize(760, 540)
        self.setStyleSheet("""
            QMainWindow { background-color: #0b0f19; }
            QLabel { color: #f1f5f9; font-family: 'Segoe UI', Arial, sans-serif; }
            QTextEdit { background-color: #111827; color: #38bdf8; border: 1px solid #1e293b; border-radius: 6px; font-family: 'Consolas', monospace; font-size: 12px; padding: 10px; }
            QProgressBar { border: 1px solid #1e293b; border-radius: 6px; background-color: #111827; text-align: center; color: #f8fafc; font-weight: 600; }
            QProgressBar::chunk { background-color: #2563eb; border-radius: 5px; }
            QPushButton { background-color: #0284c7; color: #ffffff; font-weight: 600; font-size: 12px; border-radius: 6px; padding: 10px 14px; border: none; }
            QPushButton:hover { background-color: #0369a1; }
            QFrame { background-color: #111827; border-radius: 8px; border: 1px solid #1e293b; }
        """)

        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        header = QFrame(self)
        h_layout = QVBoxLayout(header)
        title = QLabel("GridWatcher v0.3 - Regional TinyML & Cluster Utility", self)
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setStyleSheet("color: #38bdf8;")
        h_layout.addWidget(title)
        sub = QLabel("10-Feature Flat-Node Ensemble | Pre-Drop Signature Gate | HMAC-SHA256 Auth", self)
        sub.setStyleSheet("color: #94a3b8;")
        h_layout.addWidget(sub)
        layout.addWidget(header)

        btn_row = QHBoxLayout()
        btn_retrain = QPushButton("RETRAIN 10-FEATURE MODEL", self)
        btn_retrain.setStyleSheet("background-color: #16a34a;")
        btn_retrain.clicked.connect(self.start_pipeline)
        btn_row.addWidget(btn_retrain)

        btn_brain = QPushButton("OPEN 10-FEATURE SIMULATOR", self)
        btn_brain.clicked.connect(self.open_brain_viewer)
        btn_row.addWidget(btn_brain)

        btn_web = QPushButton("OPEN WEB CONSOLE (/admin)", self)
        btn_web.clicked.connect(lambda: webbrowser.open("http://127.0.0.1:8000/admin"))
        btn_row.addWidget(btn_web)
        layout.addLayout(btn_row)

        self.txt_terminal = QTextEdit(self)
        self.txt_terminal.setReadOnly(True)
        layout.addWidget(self.txt_terminal)

        self.lbl_status = QLabel("Status: Ready", self)
        layout.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

    def open_brain_viewer(self):
        dlg = MLBrainDialog(self)
        dlg.exec() if hasattr(dlg, "exec") else dlg.exec_()

    def start_pipeline(self):
        self.worker = RetrainerWorker()
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.log_signal.connect(self.txt_terminal.append)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def update_progress(self, val, msg):
        self.progress_bar.setValue(val)
        self.lbl_status.setText(msg)

    def on_finished(self, ok, msg):
        self.lbl_status.setText(msg)


def main():
    app = QApplication(sys.argv)
    window = IndustrialMLDashboard()
    window.show()
    sys.exit(app.exec() if hasattr(app, "exec") else app.exec_())


if __name__ == "__main__":
    main()
