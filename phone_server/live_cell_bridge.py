#!/usr/bin/env python3
"""
GridWatcher: Live ADB-Netcat Cellular Telemetry Bridge
Description: Reads real-time LTE signal strength (dBm) from the phone via ADB USB 
and pipes HTTP POST packets directly through the phone's Wi-Fi interface to the ESP32 Base Station.
"""

import subprocess
import re
import time
import sys
from datetime import datetime

ADB_PATH = r"c:\Users\school\Downloads\platform-tools\adb.exe"

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
    except Exception as e:
        print(f"[ERROR] Reading signal: {e}", flush=True)
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
            return True
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Sent {dbm} dBm -> ESP32 Response: {res.stdout.strip()}", flush=True)
            return True
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] FAIL sending signal {dbm} dBm: {e}", flush=True)
        return False

def main():
    print("=" * 65, flush=True)
    print("  GridWatcher Live ADB-Netcat Cellular Telemetry Bridge", flush=True)
    print("  Phone -> USB -> Netcat Wi-Fi -> ESP32 Base Station (192.168.4.1)", flush=True)
    print("=" * 65, flush=True)

    while True:
        dbm = get_live_rsrp()
        if dbm != -999:
            send_signal_to_esp32(dbm)
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Searching for active cellular signal...", flush=True)
        time.sleep(2)

if __name__ == "__main__":
    main()
