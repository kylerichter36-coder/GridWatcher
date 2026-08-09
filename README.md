# ⚡ GridWatcher: Off-Grid & Cellular Solar Grid Monitor

GridWatcher is an advanced off-grid electrical grid monitoring system combining ESP32-C6 hardware, 868MHz LoRa radio telemetry, real ZMPT101B 230V AC True RMS sampling, an Orange Pi PC + eMMC Home Assistant server, and an automated Windows Machine Learning retrainer.

---

## 🔒 Security & Wi-Fi Configuration (`secrets.h`)

To protect user privacy, Wi-Fi credentials are **never committed to GitHub**.

When cloning this repository for local compilation in Arduino IDE:

1. Navigate to the `home_sender/` directory.
2. Copy `secrets.h.example` to `secrets.h`:
   ```bash
   cp home_sender/secrets.h.example home_sender/secrets.h
   ```
3. Open `secrets.h` in your editor and enter your local Wi-Fi credentials:
   ```cpp
   #define SECRET_WIFI_SSID "YOUR_WIFI_SSID"
   #define SECRET_WIFI_PASS "YOUR_WIFI_PASSWORD"
   ```
4. Compile and upload `home_sender.ino` using Arduino IDE! `secrets.h` is protected by `.gitignore` and will never be pushed online.

---

## 🚀 System Architecture

* **ESP32 Base Station (`home_sender.ino`):** True RMS ZMPT101B 230V AC voltage & 50Hz sampling, SX1262 868MHz LoRa transmission, and Direct GitHub HTTPS Auto-OTA self-flashing engine.
* **Orange Pi PC + Home Server:** Armbian Linux running standalone from **internal 8GB eMMC flash memory** with 2.4GB expanded ZRAM/Swap space. Runs Home Assistant (`:8123`) and ESPHome (`:6052`) via Docker Compose.
* **Windows ML Retrainer:** Native Windows Toast notification & dark-mode GUI (`gridwatcher_ml_gui.py`) that retrains Scikit-Learn Random Forest models on grid telemetry and syncs C++ decision tree weights to GitHub.
