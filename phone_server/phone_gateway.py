#!/usr/bin/env python3
"""
GridWatcher: Termux Phone Gateway & Telemetry Server
Description: Runs on the old Android smartphone in Termux.
- Reads live cellular signal strength (dBm) via Termux API.
- Posts signal strength to the ESP32 Base Station HTTP endpoint (/signal).
- Listens for SMS trigger requests and logs data to local CSV for future ML training.
"""

import subprocess
import json
import time
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime

# ESP32 Base Station IP (Default SoftAP IP is 192.168.4.1)
ESP32_HOST = "http://192.168.4.1/signal"

# Data Logging File for ML Dataset
DATA_LOG_FILE = "gridwatcher_telemetry.csv"

def init_csv_log():
    if not os.path.exists(DATA_LOG_FILE):
        with open(DATA_LOG_FILE, "w") as f:
            f.write("timestamp,cell_dbm,esp_connected\n")

def log_telemetry(dbm, esp_success):
    init_csv_log()
    timestamp = datetime.now().isoformat()
    with open(DATA_LOG_FILE, "a") as f:
        f.write(f"{timestamp},{dbm},{1 if esp_success else 0}\n")

def get_cellular_signal_dbm():
    """
    Reads raw cellular dBm using termux-cellularinfo or dumpsys telephony.
    """
    # Method 1: Try termux-cellularinfo
    try:
        result = subprocess.run(['termux-cellularinfo'], capture_output=True, text=True, timeout=3)
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if isinstance(data, list) and len(data) > 0:
                dbm = data[0].get('dbm') or data[0].get('signal_strength') or data[0].get('rsrp')
                if dbm is not None and dbm != 2147483647:
                    return int(dbm)
            elif isinstance(data, dict):
                dbm = data.get('dbm') or data.get('signal_strength') or data.get('rsrp')
                if dbm is not None and dbm != 2147483647:
                    return int(dbm)
    except Exception:
        pass

    # Method 2: Fallback to Android System Telephony Registry (100% reliable)
    try:
        result = subprocess.run(['dumpsys', 'telephony.registry'], capture_output=True, text=True, timeout=3)
        if result.returncode == 0 and result.stdout.strip():
            import re
            # Match rsrp=-109 or rssi=-85
            rsrp_match = re.search(r'rsrp\s*=\s*(-?\d+)', result.stdout)
            if rsrp_match:
                val = int(rsrp_match.group(1))
                if val != 2147483647 and val < 0:
                    return val
            rssi_match = re.search(r'rssi\s*=\s*(-?\d+)', result.stdout)
            if rssi_match:
                val = int(rssi_match.group(1))
                if val != 2147483647 and val < 0:
                    return val
    except Exception as e:
        pass

    return -999

def send_signal_to_esp32(dbm):
    """
    POSTs the cellular dBm value to the ESP32 Base Station webserver endpoint.
    """
    try:
        data = urllib.parse.urlencode({'value': dbm}).encode('utf-8')
        req = urllib.request.Request(ESP32_HOST, data=data, method='POST')
        with urllib.request.urlopen(req, timeout=3) as resp:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] OK: Sent {dbm} dBm to ESP32 Base Station.")
            return True
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] FAIL: Could not reach ESP32 at {ESP32_HOST} ({e})")
        return False

def send_sms_alert(phone_number, message):
    """
    Sends an SMS alert to your phone via Termux API.
    """
    try:
        print(f"[SMS ALERT] Sending to {phone_number}: {message}")
        subprocess.run(['termux-sms-send', '-n', phone_number, message], check=True)
        print("[SMS ALERT] Sent successfully!")
    except Exception as e:
        print(f"[SMS ALERT FAIL] Could not send SMS: {e}")

def main():
    print("=" * 60)
    print("  GridWatcher Termux Cellular Gateway & Logger")
    print(f"  Target ESP32: {ESP32_HOST}")
    print("=" * 60)

    while True:
        dbm = get_cellular_signal_dbm()
        if dbm != -999:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Live Cell Signal: {dbm} dBm")
            success = send_signal_to_esp32(dbm)
            log_telemetry(dbm, success)
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Warning: Cellular info unavailable. Ensure Termux:API app is installed and granted permissions.")
            log_telemetry(-999, False)
            
        time.sleep(3)

if __name__ == "__main__":
    main()
