#!/usr/bin/env python3
"""
GridWatcher: Live Cellular Telemetry Bridge & ML Dataset Logger — v3 Optimized
Fixes:
- ADB connection check throttled to every 30s (was every 2s — 15x fewer subprocess calls)
- Phone battery read cached for 60s (was every 2s)
- init_csv() called once at startup only
- Phone sdcard writes batched every 5 minutes (was every row — massive ADB reduction)
- Graceful Ctrl+C shutdown (adb disconnect + clean exit)
- /status web page showing live system health
"""

import subprocess
import re
import time
import os
import csv
import signal
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import urllib.parse
from datetime import datetime

ADB_PATH  = r"c:\Users\school\Downloads\platform-tools\adb.exe"
ESP32_HOST = "http://192.168.4.1"
CSV_FILE   = "gridwatcher_dataset.csv"
PORT       = 8080

# Wireless ADB fallback — phone IP when on ESP32 AP
PHONE_IP = "192.168.4.2"

# ==============================================================================
# STATE — cached values to reduce ADB subprocess frequency
# ==============================================================================
_last_adb_check   = 0
_last_batt_read   = 0
_cached_batt      = -1
_adb_check_interval = 30     # Check ADB connection every 30 seconds
_batt_interval    = 60       # Read phone battery every 60 seconds

# Batched phone sdcard writes
_sdcard_buffer    = []
_last_sdcard_push = 0
_sdcard_push_interval = 300  # Push to phone every 5 minutes

# Stats for the /status page
_stats = {
    "last_dbm"      : -999,
    "last_batt"     : -1,
    "rows_logged"   : 0,
    "last_success"  : "never",
    "fail_streak"   : 0,
    "start_time"    : datetime.now().isoformat(),
}

_shutdown = False

# ==============================================================================
# GRACEFUL SHUTDOWN
# ==============================================================================
def handle_shutdown(sig, frame):
    global _shutdown
    _shutdown = True
    print(f"\n[{_ts()}] Shutting down GridWatcher Bridge...")
    try:
        subprocess.run([ADB_PATH, 'disconnect'], capture_output=True, timeout=3)
        print(f"[{_ts()}] ADB disconnected cleanly.")
    except Exception:
        pass

signal.signal(signal.SIGINT,  handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

def _ts():
    return datetime.now().strftime('%H:%M:%S')

# ==============================================================================
# CSV INIT — called ONCE at startup
# ==============================================================================
def init_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, 'w', newline='') as f:
            csv.writer(f).writerow(['timestamp', 'voltage_v', 'frequency_hz'])

# ==============================================================================
# ADB CONNECTION — throttled to every 30 seconds
# ==============================================================================
def ensure_adb_connection():
    global _last_adb_check
    now = time.time()
    if now - _last_adb_check < _adb_check_interval:
        return
    _last_adb_check = now

    try:
        res = subprocess.run([ADB_PATH, 'devices'], capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            lines = [l for l in res.stdout.splitlines() if 'device' in l and 'List' not in l]
            if not lines:
                print(f"[{_ts()}] USB ADB not found. Trying Wireless ADB {PHONE_IP}:5555...")
                subprocess.run([ADB_PATH, 'connect', f'{PHONE_IP}:5555'],
                               capture_output=True, text=True, timeout=5)
    except Exception:
        pass

# ==============================================================================
# CELL SIGNAL READ
# ==============================================================================
def get_live_rsrp():
    try:
        res = subprocess.run(
            [ADB_PATH, 'shell', 'dumpsys', 'telephony.registry'],
            capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and res.stdout:
            for match in re.findall(r'rsrp\s*=\s*(-?\d+)', res.stdout):
                val = int(match)
                if val != 2147483647 and val < 0:
                    return val
            for match in re.findall(r'rssi\s*=\s*(-?\d+)', res.stdout):
                val = int(match)
                if val != 2147483647 and val < 0:
                    return val
    except Exception:
        pass
    return -999

# ==============================================================================
# PHONE BATTERY READ — cached for 60 seconds
# ==============================================================================
def get_phone_battery():
    global _last_batt_read, _cached_batt
    now = time.time()
    if now - _last_batt_read < _batt_interval and _cached_batt != -1:
        return _cached_batt
    _last_batt_read = now
    try:
        res = subprocess.run(
            [ADB_PATH, 'shell', 'dumpsys', 'battery'],
            capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout:
            m = re.search(r'level:\s*(\d+)', res.stdout)
            if m:
                _cached_batt = int(m.group(1))
                return _cached_batt
    except Exception:
        pass
    return _cached_batt  # Return last known value on failure

# ==============================================================================
# TELEMETRY LOGGING
# ==============================================================================
def log_telemetry_row(voltage=230.0, freq=50.0):
    global _sdcard_buffer, _last_sdcard_push
    timestamp = datetime.now().isoformat()
    row = f"{timestamp},{voltage},{freq}"
    _stats["rows_logged"] += 1

    # Write to local PC CSV file
    with open(CSV_FILE, 'a', newline='') as f:
        f.write(row + "\n")

    # Buffer the row for batched phone push
    _sdcard_buffer.append(row)

    # Push the batch to phone every 5 minutes
    now = time.time()
    if now - _last_sdcard_push >= _sdcard_push_interval and _sdcard_buffer:
        batch = "\n".join(_sdcard_buffer)
        try:
            subprocess.run(
                [ADB_PATH, 'shell', f'echo "{batch}" >> /sdcard/Download/gridwatcher_dataset.csv'],
                timeout=5)
            print(f"[{_ts()}] Pushed {len(_sdcard_buffer)} rows to phone sdcard.")
            _sdcard_buffer.clear()
            _last_sdcard_push = now
        except Exception as e:
            print(f"[{_ts()}] sdcard push failed: {e}")

# ==============================================================================
# SEND SIGNAL TO ESP32
# ==============================================================================
def send_signal_to_esp32(dbm, phone_batt):
    body = f"value={dbm}&phone_battery={phone_batt}"
    content_len = len(body)
    http_request = (f"POST /signal HTTP/1.1\\r\\nHost: 192.168.4.1\\r\\n"
                    f"Content-Type: application/x-www-form-urlencoded\\r\\n"
                    f"Content-Length: {content_len}\\r\\nConnection: close\\r\\n\\r\\n{body}")
    cmd = f"echo -e '{http_request}' | nc -w 2 192.168.4.1 80"
    try:
        res = subprocess.run([ADB_PATH, 'shell', cmd],
                             capture_output=True, text=True, timeout=4)
        success = "200 OK" in res.stdout or "OK" in res.stdout
        if success:
            _stats["last_dbm"]    = dbm
            _stats["last_batt"]   = phone_batt
            _stats["last_success"] = _ts()
            _stats["fail_streak"] = 0
            print(f"[{_ts()}] Cell {dbm}dBm | PhoneBatt {phone_batt}% -> ESP32 OK", flush=True)
        else:
            _stats["fail_streak"] += 1
            print(f"[{_ts()}] ESP32 response: {res.stdout.strip()} (fails: {_stats['fail_streak']})", flush=True)
        log_telemetry_row()
        return success
    except Exception as e:
        _stats["fail_streak"] += 1
        print(f"[{_ts()}] SEND FAIL: {e}", flush=True)
        return False

# ==============================================================================
# WEB SERVER — CSV download + /status health page
# ==============================================================================
def start_web_server():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # Suppress per-request console spam

        def do_GET(self):
            if self.path in ('/', '/download'):
                if os.path.exists(CSV_FILE):
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/csv')
                    self.send_header('Content-Disposition', f'attachment; filename="{CSV_FILE}"')
                    self.end_headers()
                    with open(CSV_FILE, 'rb') as f:
                        self.wfile.write(f.read())
                else:
                    self.send_error(404, "Dataset CSV not created yet.")

            elif self.path == '/status':
                uptime_s = int((datetime.now() - datetime.fromisoformat(_stats["start_time"])).total_seconds())
                html = f"""<!DOCTYPE html><html>
<head><title>GridWatcher Bridge Status</title>
<style>body{{font-family:monospace;background:#111;color:#0f0;padding:20px;}}
td{{padding:4px 12px;}} .good{{color:#0f0;}} .warn{{color:#ff0;}} .bad{{color:#f00;}}</style>
<meta http-equiv="refresh" content="5"></head>
<body>
<h2>GridWatcher Bridge Status</h2>
<table>
<tr><td>Cell Signal</td><td class="{'good' if _stats['last_dbm'] > -110 else 'warn'}">{_stats['last_dbm']} dBm</td></tr>
<tr><td>Phone Battery</td><td>{_stats['last_batt']}%</td></tr>
<tr><td>Rows Logged</td><td>{_stats['rows_logged']}</td></tr>
<tr><td>Last Success</td><td>{_stats['last_success']}</td></tr>
<tr><td>Fail Streak</td><td class="{'bad' if _stats['fail_streak'] > 3 else 'good'}">{_stats['fail_streak']}</td></tr>
<tr><td>Uptime</td><td>{uptime_s // 3600:02d}:{(uptime_s % 3600) // 60:02d}:{uptime_s % 60:02d}</td></tr>
<tr><td>Buffered sdcard rows</td><td>{len(_sdcard_buffer)}</td></tr>
</table>
<p><a href="/download" style="color:#0ff">Download Dataset CSV</a></p>
</body></html>"""
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(html.encode())
            else:
                self.send_error(404)

    httpd = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f"[{_ts()}] Web server: http://localhost:{PORT}/download | http://localhost:{PORT}/status")
    httpd.serve_forever()

# ==============================================================================
# MAIN
# ==============================================================================
def main():
    global _last_sdcard_push
    print("=" * 70)
    print("  GridWatcher Telemetry Bridge & ML Dataset Logger v3")
    print(f"  CSV: {CSV_FILE}  |  Web: http://localhost:{PORT}")
    print(f"  ADB check: every {_adb_check_interval}s  |  Batt cache: {_batt_interval}s  |  sdcard push: every {_sdcard_push_interval}s")
    print("=" * 70)

    init_csv()  # Called once only
    _last_sdcard_push = time.time()

    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()

    while not _shutdown:
        ensure_adb_connection()  # Throttled — only runs every 30s
        dbm        = get_live_rsrp()
        phone_batt = get_phone_battery()  # Cached — only polls ADB every 60s

        if dbm != -999:
            send_signal_to_esp32(dbm, phone_batt)
        else:
            print(f"[{_ts()}] Searching for cell signal... (PhoneBatt: {phone_batt}%)", flush=True)

        time.sleep(2)

    print(f"[{_ts()}] Bridge stopped cleanly.")

if __name__ == "__main__":
    main()
