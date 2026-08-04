#!/usr/bin/env python3
"""
GridWatcher: Automated Wireless OTA Flashing Script
Pushes compiled .bin firmware files over WiFi to the ESP32 Base Station or Handheld Dashboard.
Usage:
    python ota_push.py sender path/to/firmware.bin
    python ota_push.py dashboard path/to/firmware.bin
"""

import sys
import os

try:
    import requests
except ImportError:
    import urllib.request
    import urllib.parse

TARGETS = {
    "sender": "http://192.168.4.1/update",
    "dashboard": "http://192.168.4.100/update",
}

def main():
    if len(sys.argv) < 3:
        print("Usage: python ota_push.py <target: sender|dashboard|IP> <path_to_bin_file>")
        sys.exit(1)

    target = sys.argv[1].lower()
    bin_path = sys.argv[2]

    if not os.path.exists(bin_path):
        print(f"Error: Firmware file '{bin_path}' not found!")
        sys.exit(1)

    url = TARGETS.get(target, target if target.startswith("http") else f"http://{target}/update")

    print(f"[OTA] Uploading '{bin_path}' to {url}...")

    try:
        import requests
        with open(bin_path, 'rb') as f:
            files = {'update': (os.path.basename(bin_path), f, 'application/octet-stream')}
            r = requests.post(url, files=files, timeout=30)
            if r.status_code == 200 and "OK" in r.text:
                print("[OTA] SUCCESS! Firmware successfully flashed over WiFi. ESP32 is rebooting...")
            else:
                print(f"[OTA] FAILED: Server returned HTTP {r.status_code}: {r.text}")
    except ImportError:
        # Fallback using standard library boundary multipart POST
        boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
        with open(bin_path, 'rb') as f:
            content = f.read()
        
        body = (
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="update"; filename="{os.path.basename(bin_path)}"\r\n'
            f'Content-Type: application/octet-stream\r\n\r\n'
        ).encode('utf-8') + content + f'\r\n--{boundary}--\r\n'.encode('utf-8')

        req = urllib.request.Request(url, data=body)
        req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
        
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = resp.read().decode('utf-8')
                if "OK" in result:
                    print("[OTA] SUCCESS! Firmware successfully flashed over WiFi. ESP32 is rebooting...")
                else:
                    print(f"[OTA] Response: {result}")
        except Exception as e:
            print(f"[OTA] Error: {e}")

if __name__ == '__main__':
    main()
