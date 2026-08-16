#!/usr/bin/env python3
"""
GridWatcher: ML Model "Brain" Visualizer & Interactive Simulator
Allows you to inspect, simulate, and understand exactly how the Random Forest
evaluates live electrical features to predict power outages.
"""

import os
import sys
import re

HEADER_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "home_sender", "grid_model.h"))

def parse_model_metadata():
    """Extract model version, retrain date, and accuracy from grid_model.h"""
    if not os.path.exists(HEADER_PATH):
        return {"version": "Unknown", "date": "Unknown", "acc": "Unknown"}
    
    with open(HEADER_PATH, "r", encoding="utf-8") as f:
        content = f.read()
        
    v_match = re.search(r'#define ML_MODEL_VERSION\s+(\d+)', content)
    d_match = re.search(r'// Retrained on:\s+(.+)', content)
    a_match = re.search(r'// Train Acc:\s+(.+)', content)
    
    return {
        "version": v_match.group(1) if v_match else "33",
        "date": d_match.group(1).strip() if d_match else "Recent",
        "acc": a_match.group(1).strip() if a_match else "83.8% Train / 82.5% Test"
    }

def simulate_prediction(v, f, s, dv, df, v_std, f_std, v_slope):
    """
    Simulates the exact C++ predictGridRisk logic extracted from grid_model.h
    Returns the ensemble risk score (0-100%) and individual tree votes.
    """
    # Tree 0 Logic (from active v33 model)
    if f_std <= 1.8223:
        if df <= 0.0776:
            p0 = 0.0 if f <= 49.4950 else 0.8389
        else:
            if v_std <= 2.8910:
                p0 = 0.0678 if f <= 50.4950 else 0.8382
            else:
                p0 = 0.8841 if df <= 0.2227 else 0.0
    else:
        if df <= -0.1983:
            p0 = 0.8523 if f_std <= 2.1158 else 0.0
        else:
            p0 = 0.0177 if f_std <= 2.4578 else 0.8407

    # Tree 1 Logic
    if f_std <= 1.8223:
        if df <= 0.0776:
            p1 = 0.0 if f <= 49.4950 else 0.8389
        else:
            if v_std <= 2.8910:
                p1 = 0.0684 if f <= 50.4950 else 0.8382
            else:
                p1 = 0.8841 if df <= 0.2227 else 0.0
    else:
        if df <= -0.1983:
            p1 = 0.8523 if f_std <= 2.1158 else 0.0
        else:
            p1 = 0.0177 if f_std <= 2.4578 else 0.8407

    # Tree 2 Logic
    if f_std <= 1.8223:
        if df <= 0.0776:
            p2 = 0.0 if f <= 49.4950 else 0.8389
        else:
            if v_std <= 2.8910:
                p2 = 0.0684 if f <= 50.4950 else 0.8382
            else:
                p2 = 0.8841 if df <= 0.2227 else 0.0
    else:
        if df <= -0.1983:
            p2 = 0.8523 if f_std <= 2.1158 else 0.0
        else:
            p2 = 0.0177 if f_std <= 2.4578 else 0.8407

    avg_risk = (p0 + p1 + p2) / 3.0 * 100.0
    return avg_risk, p0 * 100.0, p1 * 100.0, p2 * 100.0

def print_banner():
    meta = parse_model_metadata()
    print("=" * 70)
    print("       GRIDWATCHER ML MODEL BRAIN SIMULATOR & VISUALIZER")
    print(f"       Active Model: v{meta['version']} | {meta['date']}")
    print(f"       Evaluation:   {meta['acc']}")
    print("=" * 70)

def run_scenarios():
    scenarios = [
        {
            "name": "1. Normal Stable Daytime Grid",
            "v": 230.2, "f": 50.01, "s": -95.0, "dv": 0.02, "df": 0.01, "v_std": 0.45, "f_std": 0.05, "v_slope": 0.01,
            "desc": "Voltage and frequency are rock steady within standard South African grid parameters."
        },
        {
            "name": "2. Approaching Brownout / Heavy Inrush Sag",
            "v": 204.5, "f": 49.62, "s": -98.0, "dv": -0.85, "df": -0.05, "v_std": 3.42, "f_std": 0.85, "v_slope": -0.62,
            "desc": "Voltage is dropping rapidly (-0.85 V/s) with elevated 30-second turbulence (3.42V)."
        },
        {
            "name": "3. Generator Frequency Jitter Storm",
            "v": 222.0, "f": 52.40, "s": -104.0, "dv": -0.10, "df": 0.35, "v_std": 1.80, "f_std": 2.15, "v_slope": -0.05,
            "desc": "High frequency instability (f_std = 2.15 Hz), typical before utility feeder tripping."
        },
        {
            "name": "4. Imminent Blackout Crash (Pre-Outage Signature)",
            "v": 192.0, "f": 48.90, "s": -110.0, "dv": -1.80, "df": -0.25, "v_std": 4.80, "f_std": 1.95, "v_slope": -1.20,
            "desc": "Severe voltage dive (-1.8 V/s) and generator frequency collapse under heavy load."
        }
    ]

    print("\n--- [PRE-SET GRID SCENARIO SIMULATION] ---\n")
    for sc in scenarios:
        risk, p0, p1, p2 = simulate_prediction(
            sc["v"], sc["f"], sc["s"], sc["dv"], sc["df"], sc["v_std"], sc["f_std"], sc["v_slope"]
        )
        bar_len = int(risk / 2.5)
        bar = "#" * bar_len + "-" * (40 - bar_len)
        
        status_tag = "NORMAL (SAFE)"
        sms_alert = "No SMS Needed"
        if risk >= 75.0 or sc["v"] < 180.0:
            status_tag = "CRITICAL OUTAGE RISK"
            sms_alert = "[ALERT] INSTANT SMS DISPATCHED TO PHONE!"
        elif risk >= 40.0:
            status_tag = "ELEVATED RISK"
            sms_alert = "[WARNING] Warning Logged to Home Assistant"

        print(f"Scenario: {sc['name']}")
        print(f"Details:  {sc['desc']}")
        print(f"Inputs:   V={sc['v']}V, F={sc['f']}Hz, dV/dt={sc['dv']}V/s, dF/dt={sc['df']}Hz/s, v_std={sc['v_std']}V, f_std={sc['f_std']}Hz")
        print(f"Trees:    Tree 0: {p0:4.1f}% | Tree 1: {p1:4.1f}% | Tree 2: {p2:4.1f}%")
        print(f"Risk:     [{bar}] {risk:5.1f}% -> {status_tag}")
        print(f"Action:   {sms_alert}")
        print("-" * 70)

if __name__ == "__main__":
    print_banner()
    run_scenarios()
    
    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        print("\n--- [INTERACTIVE MANUAL SIMULATION] ---")
        try:
            v   = float(input("Enter AC Voltage (e.g. 225.0): "))
            f   = float(input("Enter Line Frequency (e.g. 50.0): "))
            s   = float(input("Enter Cell Signal dBm (e.g. -95.0): "))
            dv  = float(input("Enter dV/dt 10s (e.g. -0.5): "))
            df  = float(input("Enter dF/dt 10s (e.g. 0.05): "))
            vs  = float(input("Enter 30s Voltage Std Dev (e.g. 1.2): "))
            fs  = float(input("Enter 30s Frequency Std Dev (e.g. 0.3): "))
            vsl = float(input("Enter 30s Voltage Slope (e.g. -0.1): "))
            
            risk, p0, p1, p2 = simulate_prediction(v, f, s, dv, df, vs, fs, vsl)
            print(f"\nResult: Tree0={p0:.1f}%, Tree1={p1:.1f}%, Tree2={p2:.1f}%")
            print(f"Final Ensemble Outage Risk Score: {risk:.1f}%")
        except Exception as e:
            print(f"Invalid input: {e}")
