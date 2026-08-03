import subprocess, time

adb_path = r"c:\Users\school\Downloads\platform-tools\adb.exe"

# 1-line python script to run inside Termux
termux_cmd = "python -c \"import urllib.request, urllib.parse; urllib.request.urlopen('http://192.168.4.1/signal', data=urllib.parse.urlencode({'value': -107}).encode()); print('+++ SENT SIGNAL TO ESP32 SUCCESSFULLY! +++')\""

print("Sending POST command into Termux...")
subprocess.run([adb_path, "shell", "input", "text", termux_cmd.replace(" ", "%s")])
subprocess.run([adb_path, "shell", "input", "keyevent", "66"])
print("Done!")
