import subprocess, re

adb_path = r"c:\Users\school\Downloads\platform-tools\adb.exe"

# 1. Read live cellular signal strength (RSRP) from phone
res_sig = subprocess.run([adb_path, 'shell', 'dumpsys telephony.registry'], capture_output=True, text=True)
rsrp_match = re.search(r'rsrp\s*=\s*(-?\d+)', res_sig.stdout)
signal_dbm = int(rsrp_match.group(1)) if rsrp_match and int(rsrp_match.group(1)) < 0 else -105

body = f"value={signal_dbm}"
content_len = len(body)

http_request = f"POST /signal HTTP/1.1\\r\\nHost: 192.168.4.1\\r\\nContent-Type: application/x-www-form-urlencoded\\r\\nContent-Length: {content_len}\\r\\nConnection: close\\r\\n\\r\\n{body}"

cmd = f"echo -e '{http_request}' | nc -w 3 192.168.4.1 80"

print(f"Sending live cell signal ({signal_dbm} dBm) from phone to ESP32 via netcat...")
res = subprocess.run([adb_path, "shell", cmd], capture_output=True, text=True)
print("ESP32 Response:\n", res.stdout)
