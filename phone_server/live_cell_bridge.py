#!/usr/bin/env python3
"""
GridWatcher: Live Cellular Telemetry Bridge & ML Dataset Logger
Description:
1. Reads real-time cellular signal strength (RSRP dBm) from the phone via ADB USB.
2. Posts signal strength to the ESP32 Base Station (192.168.4.1/signal).
3. Automatically logs time-series grid telemetry into gridwatcher_dataset.csv for ML training.
4. Hosts a web dashboard and CSV download server on port 8080 for easy access from your big PC!
"""

import subprocess
import re
import time
import os
import csv
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.request
import urllib.parse
from datetime import datetime

ADB_PATH = r"c:\Users\school\Downloads\platform-tools\adb.exe"
ESP32_HOST = "http://192.168.4.1"
CSV_FILE = "gridwatcher_dataset.csv"
PORT = 8080

def init_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'cell_dbm', 'voltage_v', 'frequency_hz', 'base_battery_pct', 'sequence', 'outage_flag'])

def log_telemetry_row(cell_dbm, voltage=230.0, freq=50.0, batt=100, seq=0):
    init_csv()
    # Outage flag: 1 if voltage drops below 180V or frequency drops below 47Hz, else 0
    outage_flag = 1 if (voltage < 180.0 or freq < 47.0) else 0
    timestamp = datetime.now().isoformat()
    row = f"{timestamp},{cell_dbm},{voltage},{freq},{batt},{seq},{outage_flag}"
    
    # Log to local PC file
    with open(CSV_FILE, 'a', newline='') as f:
        f.write(row + "\n")
        
    # Also log to phone's /sdcard/Download so user can pull it via USB
    try:
        subprocess.run([ADB_PATH, 'shell', f'echo "{row}" >> /sdcard/Download/gridwatcher_dataset.csv'], timeout=2)
    except Exception as e:
        print(f"Failed to log to phone sdcard: {e}")

def get_live_rsrp():
    try:
        res = subprocess.run([ADB_PATH, 'shell', 'dumpsys', 'telephony.registry'], capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and res.stdout:
            rsrp_matches = re.findall(r'rsrp\s*=\s*(-?\d+)', res.stdout)
            for val_str in rsrp_matches:
                val = int(val_str)
                if val != 2147483647 and val < 0:
                    return val
            rssi_matches = re.findall(r'rssi\s*=\s*(-?\d+)', res.stdout)
            for val_str in rssi_matches:
                val = int(val_str)
                if val != 2147483647 and val < 0:
                    return val
    except Exception:
        pass
    return -999

def send_signal_to_esp32(dbm):
    body = f"value={dbm}"
    content_len = len(body)
    http_request = f"POST /signal HTTP/1.1\\r\\nHost: 192.168.4.1\\r\\nContent-Type: application/x-www-form-urlencoded\\r\\nContent-Length: {content_len}\\r\\nConnection: close\\r\\n\\r\\n{body}"
    cmd = f"echo -e '{http_request}' | nc -w 2 192.168.4.1 80"
    
    try:
        res = subprocess.run([ADB_PATH, 'shell', cmd], capture_output=True, text=True, timeout=4)
        if "200 OK" in res.stdout or "OK" in res.stdout:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] SUCCESS: Live Cell Signal {dbm} dBm delivered to ESP32 Base Station!", flush=True)
            log_telemetry_row(dbm)
            return True
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Sent {dbm} dBm -> ESP32 Response: {res.stdout.strip()}", flush=True)
            log_telemetry_row(dbm)
            return True
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] FAIL sending signal {dbm} dBm: {e}", flush=True)
        return False

def start_web_server():
    """
    Hosts a lightweight web server on port 8080 so any PC on the network 
    can view or download gridwatcher_dataset.csv with one click.
    """
    class CSVHandler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/' or self.path == '/download':
                if os.path.exists(CSV_FILE):
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/csv')
                    self.send_header('Content-Disposition', f'attachment; filename="{CSV_FILE}"')
                    self.end_headers()
                    with open(CSV_FILE, 'rb') as f:
                        self.wfile.write(f.read())
                else:
                    self.send_error(404, "Dataset CSV not created yet.")
            else:
                super().do_GET()

    server = HTTPServer(('0.0.0.0', PORT), CSVHandler)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] ML Dataset Server started at http://localhost:{PORT}/download", flush=True)
    server.serve_forever()

def main():
    print("=" * 70, flush=True)
    print("  GridWatcher Telemetry Bridge & ML Dataset Logger")
    print(f"  Live CSV Logger: {CSV_FILE}")
    print(f"  Dataset Web Download Server: http://localhost:{PORT}/download")
    print("=" * 70, flush=True)

    init_csv()

    # Start CSV Download Web Server in background thread
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()

    while True:
        dbm = get_live_rsrp()
        if dbm != -999:
            send_signal_to_esp32(dbm)
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Searching for active cellular signal...", flush=True)
        time.sleep(2)

if __name__ == "__main__":
    main()
