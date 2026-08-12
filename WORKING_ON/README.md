# Active Development & Work In Progress

This directory tracks active development status, system verification, and the engineering roadmap for the GridWatcher project.

---

## Current Status: GridWatcher V1 (Functional Prototype)

### Completed V1 Accomplishments

1. **Dual-Layer Anomaly & Predictive Risk Engine**
   - **Layer 1 (Deterministic Rules)**: Implemented C++ threshold state machine in `home_sender.ino` (`BLACKOUT`, `SURGE`, `BROWNOUT_SAG`, `FREQ_JITTER`, `NORMAL`) using strict evaluation precedence.
   - **Layer 2 (Experimental ML Risk Model)**: Implemented Random Forest model (`grid_model.h`) operating on 8 total inputs (voltage, frequency, cell signal, `dV/dt_10s`, `dF_dt_10s`, `v_std_30s`, `f_std_30s`, `v_slope_30s`).
   - **Pure Timestamp Search**: Implemented pure timestamp-based search (`timestamp_ms`) in `computeRollingFeatures()` for 10s and 30s rate of change and regression slope.

2. **12-Byte Binary LoRa Protocol Migration**
   - Migrated from legacy ASCII string transmission (`V:230.1,F:50.0...`) to a 12-byte binary packed struct (`GridPacket`).
   - Achieved an **approximately 2.8x reduction in payload data size** ($34 / 12 \approx 2.83\times$, ~8ms transmission duration), complying with EU868 and US915 duty-cycle budgets.
   - Validates `0x4757` magic sync header in receiver firmware to verify packet structure and reject malformed/unrelated RF data.

3. **Machine Learning Pipeline & Evaluation**
   - Implemented continuous 0–30s forward-looking target labeling in `gridwatcher_ml_gui.py` for early-warning outage risk classification.
   - Chronological 80/20 train/test holdout split evaluating **85.83% Train Accuracy / 77.97% Test Holdout Accuracy** (`v26`).
   - Automated Scikit-Learn tree export directly into C++ conditional logic (`tree0`, `tree1`, `tree2`).

4. **Multi-Machine Deployment & Security Refinements**
   - Configurable AP/OTA passwords (`AP_PASSWORD`, `OTA_PASSWORD`) and environment/json server credentials (`GRIDWATCHER_PI_PASS` / `secrets.json`).
   - Updated `install_startup.bat` to automatically download standalone `arduino-cli` and required Arduino libraries (`RadioLib`, `Adafruit GFX`, `Adafruit ST7789`, `Adafruit BusIO`).
   - Direct dual-stage Auto-OTA engine checking local server (`192.168.3.47:5000`) with direct GitHub HTTPS fallback.

---

## Task Verification & Component Matrix

| Component | Status | Verification Summary |
|---|---|---|
| `home_sender.ino` | Completed | Pure timestamp-based search, 30-sample ring buffer, Layer 1 state machine, Layer 2 RF integration, 12-byte binary LoRa TX. |
| `grid_model.h` | Completed | 3-tree Random Forest C++ export with 8 model inputs (`v26`). |
| `gridwatcher_dashboard2.ino` | Completed | Binary struct unpacking (12 bytes), configurable OTA password, and magic header `0x4757` verification. |
| `gridwatcher_ml_gui.py` | Completed | Gap-aware feature extraction ($\Delta t > 35s$), chronological 80/20 train/test holdout evaluation, 1-click single-binary OTA pipeline. |
| `install_startup.bat` | Completed | Standalone `arduino-cli` download, ESP32 core install, library dependency resolution. |

---

## Roadmap: Planned for V2 (Custom PCB Revision)

* **Monolithic PCB Hardware**: Replace prototype breadboard wiring with a custom 2-layer PCB.
* **Calibrated High-Voltage AC Metering**: Integrate dedicated metering IC (e.g. ADE7753 / ATM90E26) calibrated against laboratory-grade reference meters.
* **Cryptographic Security**: Hardware AES-128 payload encryption and HMAC packet signing.
* **Enclosure & Power Supply**: Custom 3D-printed DIN-rail enclosure with integrated UPS battery backup.
