#!/usr/bin/env python3
"""
GridWatcher: Standalone Termux Cellular Gateway & ML Dataset Server
Description: Runs ON THE PHONE inside Termux.
1. Reads live cellular tower signal strength (dBm).
2. Posts signal strength to the ESP32 Base Station (192.168.4.1/signal).
3. Saves time-series grid telemetry directly to the PHONE'S STORAGE (/sdcard/Download/gridwatcher_dataset.csv).
4. Hosts a 1-click HTTP download server on port 8080 on the phone so any PC on Wi-Fi can download the dataset!
"""

import subprocess
import json
import time
import os
import csv
import re
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.request
import urllib.parse
from datetime import datetime

ESP32_HOST = "http://192.168.4.1/signal"
PRIMARY_CSV = os.path.expanduser("~/gridwatcher_dataset.csv")
SDCARD_CSV = "/sdcard/Download/gridwatcher_dataset.csv"
PORT = 8080

def init_csv(filepath):
    try:
        dirname = os.path.dirname(filepath)
        if dirname and not os.path.exists(dirname):
            os.makedirs(dirname, exist_ok=True)
        if not os.path.exists(filepath):
            with open(filepath, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp', 'cell_dbm', 'voltage_v', 'frequency_hz', 'base_battery_pct', 'sequence', 'outage_flag'])
    except Exception:
        pass

def log_telemetry_row(cell_dbm, voltage=230.0, freq=50.0, batt=100, seq=0):
    init_csv(PRIMARY_CSV)
    init_csv(SDCARD_CSV)
    
    outage_flag = 1 if (voltage < 180.0 or freq < 47.0) else 0
    timestamp = datetime.now().isoformat()
    row = [timestamp, cell_dbm, voltage, freq, batt, seq, outage_flag]
    
    # Save to Termux home storage
    try:
        with open(PRIMARY_CSV, 'a', newline='') as f:
            csv.writer(f).writerow(row)
    except Exception:
        pass

    # Save to Phone Download folder (/sdcard/Download)
    try:
        with open(SDCARD_CSV, 'a', newline='') as f:
            csv.writer(f).writerow(row)
    except Exception:
        pass

def get_cellular_signal_dbm():
    """
    Reads raw cellular dBm inside Termux via termux-cellularinfo or dumpsys fallback.
    """
    try:
        result = subprocess.run(['termux-cellularinfo'], capture_output=True, text=True, timeout=3)
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if isinstance(data, list) and len(data) > 0:
                dbm = data[0].get('dbm') or data[0].get('signal_strength') or data[0].get('rsrp')
                if dbm is not None and dbm != 2147483647 and int(dbm) < 0:
                    return int(dbm)
            elif isinstance(data, dict):
                dbm = data.get('dbm') or data.get('signal_strength') or data.get('rsrp')
                if dbm is not None and dbm != 2147483647 and int(dbm) < 0:
                    return int(dbm)
    except Exception:
        pass

    try:
        result = subprocess.run(['dumpsys', 'telephony.registry'], capture_output=True, text=True, timeout=3)
        if result.returncode == 0 and result.stdout.strip():
            rsrp_matches = re.findall(r'rsrp\s*=\s*(-?\d+)', result.stdout)
            for val_str in rsrp_matches:
                val = int(val_str)
                if val != 2147483647 and val < 0:
                    return val
    except Exception:
        pass

    return -999

def send_signal_to_esp32(dbm):
    try:
        data = urllib.parse.urlencode({'value': dbm}).encode('utf-8')
        req = urllib.request.Request(ESP32_HOST, data=data, method='POST')
        with urllib.request.urlopen(req, timeout=3) as resp:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] OK: Sent {dbm} dBm to ESP32 Base Station.")
            return True
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] FAIL sending to ESP32: {e}")
        return False

def start_web_server():
    """
    Hosts an HTTP server on port 8080 on the phone so any PC on Wi-Fi can download the dataset.
    """
    class DatasetHandler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/' or self.path == '/download':
                target_file = SDCARD_CSV if os.path.exists(SDCARD_CSV) else PRIMARY_CSV
                if os.path.exists(target_file):
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/csv')
                    self.send_header('Content-Disposition', 'attachment; filename="gridwatcher_dataset.csv"')
                    self.end_headers()
                    with open(target_file, 'rb') as f:
                        self.wfile.write(f.read())
                else:
                    self.send_error(404, "Dataset CSV not created yet.")
            else:
                super().do_GET()

    server = HTTPServer(('0.0.0.0', PORT), DatasetHandler)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Phone Dataset Download Server started on port {PORT}!")
    server.serve_forever()

def main():
    print("=" * 65)
    print("  GridWatcher Standalone Phone Server & Dataset Logger")
    print(f"  Phone Dataset Path: {SDCARD_CSV}")
    print(f"  Phone Server Download Port: {PORT}")
    print("=" * 65)

    init_csv(PRIMARY_CSV)
    init_csv(SDCARD_CSV)

    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()

    while True:
        dbm = get_cellular_signal_dbm()
        if dbm != -999:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Phone Live Cell Signal: {dbm} dBm")
            success = send_signal_to_esp32(dbm)
            log_telemetry_row(dbm)
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Warning: Cellular signal info searching...")
            log_telemetry_row(-999)
            
        time.sleep(3)

if __name__ == "__main__":
    main()
