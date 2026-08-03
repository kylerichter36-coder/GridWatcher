#!/usr/bin/env python3
"""
GridWatcher: PC ADB Cellular Signal Gateway
Description: Reads real-time cellular RSRP dBm signal strength directly 
from the Android phone via ADB USB connection and streams it to the ESP32 Base Station.
"""

import subprocess
import re
import time
import os
import urllib.request
import urllib.parse
from datetime import datetime

ADB_PATH = r"c:\Users\school\Downloads\platform-tools\adb.exe"
ESP32_HOST = "http://192.168.4.1/signal"

def get_signal_via_adb():
    try:
        res = subprocess.run([ADB_PATH, 'shell', 'dumpsys telephony.registry'], capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout:
            # Look for active LTE RSRP signal strength
            rsrp_matches = re.findall(r'rsrp\s*=\s*(-?\d+)', res.stdout)
            for val_str in rsrp_matches:
                val = int(val_str)
                if val != 2147483647 and val < 0:
                    return val
            # Fallback to RSSI
            rssi_matches = re.findall(r'rssi\s*=\s*(-?\d+)', res.stdout)
            for val_str in rssi_matches:
                val = int(val_str)
                if val != 2147483647 and val < 0:
                    return val
    except Exception as e:
        print(f"[ERROR] ADB Shell error: {e}")
    return -999

def send_signal_to_esp32(dbm):
    try:
        data = urllib.parse.urlencode({'value': dbm}).encode('utf-8')
        req = urllib.request.Request(ESP32_HOST, data=data, method='POST')
        with urllib.request.urlopen(req, timeout=3) as resp:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] OK: Sent {dbm} dBm to ESP32 Base Station -> Status {resp.status}")
            return True
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] FAIL: Could not reach ESP32 at {ESP32_HOST} ({e})")
        return False

def main():
    print("=" * 60)
    print("  GridWatcher PC ADB Cellular Gateway")
    print(f"  Target ESP32: {ESP32_HOST}")
    print("=" * 60)

    while True:
        dbm = get_signal_via_adb()
        if dbm != -999:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Phone Live LTE Signal: {dbm} dBm")
            send_signal_to_esp32(dbm)
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Searching for phone cellular signal...")
        time.sleep(3)

if __name__ == "__main__":
    main()
