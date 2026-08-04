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
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import urllib.parse
import socket
from datetime import datetime

ADB_PATH  = r"c:\Users\school\Downloads\platform-tools\adb.exe"
ESP32_HOST = "http://192.168.4.1"
CSV_FILE   = "gridwatcher_dataset.csv"
PORT       = 8080

# Auto-detect if running inside Termux on Android
IS_TERMUX = "TERMUX_VERSION" in os.environ or os.path.exists("/data/data/com.termux")

# SMS Alert Settings (Only used when running in Termux)
SMS_TARGET_NUMBER = "0740999098"
_has_sent_outage_sms = False

# If in Termux, CSV is saved directly to Android's Download folder
if IS_TERMUX:
    CSV_FILE = "/sdcard/Download/gridwatcher_dataset.csv"

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
    if IS_TERMUX:
        return
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
    if IS_TERMUX:
        try:
            res = subprocess.run(["termux-telephony-cellinfo"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout:
                cells = json.loads(res.stdout)
                for cell in cells:
                    if cell.get("registered", False):
                        sig = cell.get("cell_signal_strength", {})
                        if "rsrp" in sig:
                            return sig["rsrp"]
                        elif "dbm" in sig:
                            return sig["dbm"]
        except Exception as e:
            print(f"[{_ts()}] Termux cellinfo error: {e}")
        return -999

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

    if IS_TERMUX:
        try:
            res = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout:
                data = json.loads(res.stdout)
                _cached_batt = data.get("percentage", -1)
                return _cached_batt
        except Exception as e:
            print(f"[{_ts()}] Termux battery error: {e}")
        return _cached_batt

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

    # Write directly to local file (on sdcard if in Termux)
    try:
        dir_name = os.path.dirname(CSV_FILE)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
            
        if not os.path.exists(CSV_FILE):
            with open(CSV_FILE, 'w', newline='') as f:
                f.write("timestamp,voltage_v,frequency_hz\n")
                
        with open(CSV_FILE, 'a', newline='') as f:
            f.write(row + "\n")
    except Exception as e:
        print(f"[{_ts()}] Local CSV write failed: {e}")

    # No need to push via ADB if running directly on the phone
    if IS_TERMUX:
        return

    # Buffer the row for batched phone push (Laptop mode only)
    _sdcard_buffer.append(row)
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
    global _has_sent_outage_sms
    body = f"value={dbm}&phone_battery={phone_batt}"
    content_len = len(body)

    # Resolve target IPs
    targets = []
    
    if IS_TERMUX:
        # AP default
        targets.append("192.168.4.1")
        # Hotspot default
        targets.append("192.168.43.1")
        # Scan local hotspot DHCP leases/neighbors
        try:
            with open('/proc/net/arp', 'r') as f:
                lines = f.readlines()[1:]
                for line in lines:
                    parts = line.split()
                    if parts and parts[0].count('.') == 3:
                        ip = parts[0]
                        if ip not in targets and not ip.endswith('.1'):
                            targets.append(ip)
        except Exception:
            pass
        try:
            res = subprocess.run(['ip', 'neigh'], capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    parts = line.split()
                    if parts and parts[0].count('.') == 3:
                        ip = parts[0]
                        if ip not in targets and not ip.endswith('.1'):
                            targets.append(ip)
        except Exception:
            pass
    else:
        # Laptop direct via mDNS
        sender_ip = None
        try:
            sender_ip = socket.gethostbyname("gridwatcher-sender.local")
        except Exception:
            pass
        if sender_ip:
            targets.append(sender_ip)
        targets.append("192.168.4.1")

    # 1. Try sending directly via Python urllib (works for laptop and Termux local)
    for ip in targets:
        try:
            url = f"http://{ip}/signal"
            data = urllib.parse.urlencode({"value": dbm, "phone_battery": phone_batt}).encode()
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=2) as response:
                if response.status == 200:
                    _stats["last_dbm"]    = dbm
                    _stats["last_batt"]   = phone_batt
                    _stats["last_success"] = _ts()
                    _stats["fail_streak"] = 0
                    _has_sent_outage_sms  = False  # Reset alert flag
                    print(f"[{_ts()}] [Direct via {ip}] Cell {dbm}dBm | PhoneBatt {phone_batt}% -> ESP32 OK", flush=True)
                    log_telemetry_row()
                    return True
        except Exception:
            pass

    # 2. Fallback to phone's 'nc' via ADB shell (Laptop mode only)
    if not IS_TERMUX:
        for ip in targets:
            http_request = (f"POST /signal HTTP/1.1\\r\\nHost: {ip}\\r\\n"
                            f"Content-Type: application/x-www-form-urlencoded\\r\\n"
                            f"Content-Length: {content_len}\\r\\nConnection: close\\r\\n\\r\\n{body}")
            cmd = f"echo -e '{http_request}' | nc -w 2 {ip} 80"
            try:
                res = subprocess.run([ADB_PATH, 'shell', cmd], capture_output=True, text=True, timeout=4)
                if "200 OK" in res.stdout or "OK" in res.stdout:
                    _stats["last_dbm"]    = dbm
                    _stats["last_batt"]   = phone_batt
                    _stats["last_success"] = _ts()
                    _stats["fail_streak"] = 0
                    print(f"[{_ts()}] [Phone via {ip}] Cell {dbm}dBm | PhoneBatt {phone_batt}% -> ESP32 OK", flush=True)
                    log_telemetry_row()
                    return True
            except Exception:
                pass

    _stats["fail_streak"] += 1
    print(f"[{_ts()}] SEND FAIL to all targets {targets} (fails: {_stats['fail_streak']})", flush=True)
    log_telemetry_row()

    # Outage SMS Alert (Only in Termux standalone mode)
    if IS_TERMUX and _stats["fail_streak"] == 5 and not _has_sent_outage_sms:
        _has_sent_outage_sms = True
        try:
            msg = f"GridWatcher Outage Alert! Phone lost connection to the transmitter. Cell signal was {dbm}dBm. Outage start: {_ts()}."
            subprocess.run(["termux-sms-send", "-n", SMS_TARGET_NUMBER, msg], timeout=5)
            print(f"[{_ts()}] [SMS Alert] Sent outage notification SMS to {SMS_TARGET_NUMBER}", flush=True)
        except Exception as e:
            print(f"[{_ts()}] Failed to send SMS alert: {e}", flush=True)

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
# MAIN — with auto-reconnect outer loop
# ==============================================================================
def main():
    global _last_sdcard_push, _shutdown
    
    # Find update host dynamically
    update_host = "192.168.4.1"
    try:
        resolved = socket.gethostbyname("gridwatcher-sender.local")
        if resolved:
            update_host = resolved
    except Exception:
        pass

    # Self-update: check sender hub for a new bridge script
    try:
        check = urllib.request.urlopen(
            f"http://{update_host}/bridge-update-available", timeout=3
        )
        if check.read().decode().strip() == "yes":
            print(f"[{_ts()}] Sender has a bridge update! Downloading...")
            script_path = os.path.abspath(__file__)
            tmp_path    = script_path + ".tmp"
            urllib.request.urlretrieve(f"http://{update_host}/bridge-script", tmp_path)
            os.replace(tmp_path, script_path)
            # Confirm to sender hub
            urllib.request.urlopen(
                urllib.request.Request(
                    f"http://{update_host}/device-updated?device=bridge",
                    data=b""
                ), timeout=3
            )
            print(f"[{_ts()}] Bridge updated! Restarting...")
            import sys
            os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        print(f"[{_ts()}] Hub update check skipped: {e}")

    print("=" * 70)
    print("  GridWatcher Telemetry Bridge & ML Dataset Logger v3")
    print(f"  CSV: {CSV_FILE}  |  Web: http://localhost:{PORT}")
    if IS_TERMUX:
        print("  Running: STANDALONE inside Termux on Phone")
        print("  SMS Outage Alerts: ENABLED to " + SMS_TARGET_NUMBER)
    else:
        print(f"  ADB check: every {_adb_check_interval}s  |  Batt cache: {_batt_interval}s  |  sdcard push: every {_sdcard_push_interval}s")
    print("  Auto-reconnect: ON (retries every 5s on disconnect)")
    print("=" * 70)
    print("=" * 70)

    init_csv()
    _last_sdcard_push = time.time()

    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()

    # Outer loop: keeps the bridge running forever, reconnecting on any error
    while not _shutdown:
        try:
            print(f"[{_ts()}] Bridge loop starting...")
            while not _shutdown:
                ensure_adb_connection()  # Throttled — only runs every 30s
                dbm        = get_live_rsrp()
                phone_batt = get_phone_battery()  # Cached — only polls ADB every 60s

                if dbm != -999:
                    send_signal_to_esp32(dbm, phone_batt)
                else:
                    print(f"[{_ts()}] Searching for cell signal... (PhoneBatt: {phone_batt}%)", flush=True)

                time.sleep(2)

        except KeyboardInterrupt:
            _shutdown = True
        except Exception as e:
            print(f"[{_ts()}] Bridge error: {e}. Reconnecting in 5s...")
            time.sleep(5)

    print(f"[{_ts()}] Bridge stopped cleanly.")


if __name__ == "__main__":
    main()
