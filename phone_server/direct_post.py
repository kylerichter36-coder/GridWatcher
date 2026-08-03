import subprocess

adb_path = r"c:\Users\school\Downloads\platform-tools\adb.exe"

py_code = "import urllib.request, urllib.parse; data = urllib.parse.urlencode({'value': -105}).encode('utf-8'); req = urllib.request.Request('http://192.168.4.1/signal', data=data, method='POST'); resp = urllib.request.urlopen(req, timeout=5); print('=== SUCCESS! ESP32 RESPONDED:', resp.read().decode(), '===')"

cmd = f"export PATH=/data/data/com.termux/files/usr/bin:$PATH; export LD_LIBRARY_PATH=/data/data/com.termux/files/usr/lib; python3 -c \"{py_code}\""

res = subprocess.run([adb_path, "shell", cmd], capture_output=True, text=True)
print("ADB Shell Output:\n", res.stdout)
print("ADB Shell Error:\n", res.stderr)
