# Active Development & Work In Progress

This directory tracks current active development tasks, architectural upgrades, and ongoing engineering objectives for the GridWatcher project.

---

## Current Focus: Phase 2 Rollout

### Active Objectives

1. **Dual-Layer Anomaly & Predictive Risk Engine**
   - Implemented Layer 1 deterministic threshold state machine in `home_sender.ino` (`BLACKOUT`, `SURGE`, `BROWNOUT_SAG`, `FREQ_JITTER`, `NORMAL`) using strict severity precedence.
   - Implemented Layer 2 time-series Random Forest model (`grid_model.h`) operating on dual rolling windows (10-second fast transient window and 30-second trend/dispersion window).

2. **10-Byte Binary LoRa Protocol Migration**
   - Migrated from legacy ASCII string transmission (`V:230.1,F:50.0...`) to a 10-byte binary packed struct (`GridPacket`).
   - Achieved a 3.4x reduction in RF airtime per packet (~8ms transmission duration), complying with EU868 and US915 duty-cycle constraints.
   - Added `0x4757` magic sync header validation in receiver firmware to drop unauthenticated packets.

3. **Machine Learning Pipeline Refinements**
   - Implemented continuous 0–30s forward-looking target labeling in `gridwatcher_ml_gui.py` to train early-warning outage prediction.
   - Added gap-aware rolling feature calculation to invalidate time windows containing packet loss or reset gaps ($\Delta t > 2\text{s}$).
   - Automated Scikit-Learn tree export directly into C++ conditional logic (`tree0`, `tree1`, `tree2`).

4. **Multi-Machine Deployment & Standalone Tooling**
   - Updated `install_startup.bat` to automatically download standalone `arduino-cli` and required Arduino libraries (`RadioLib`, `Adafruit GFX`, `Adafruit ST7789`, `Adafruit BusIO`).
   - Removed `handheld.bin` recompilation from the ML trainer pipeline (only `home_sender.bin` embeds model weights).

---

## Task Verification & Testing Status

| Component | Status | Description |
|---|---|---|
| `home_sender.ino` | Completed | Ring buffer, Layer 1 state machine, Layer 2 RF integration, 10-byte binary LoRa TX. |
| `grid_model.h` | Completed | 3-tree Random Forest C++ export with 8 input features. |
| `gridwatcher_dashboard2.ino` | Completed | Binary struct unpacking and magic header `0x4757` verification. |
| `gridwatcher_ml_gui.py` | Completed | Gap-aware feature extraction, 0–30s target labeling, 1-click single-binary OTA pipeline. |
| `install_startup.bat` | Completed | Standalone `arduino-cli` download, ESP32 core install, library dependency resolution. |

---

## Next Steps & Future Roadmap

* **Telemetry Logger Integration:** Update Orange Pi `/root/gridwatcher/telemetry_logger.py` to parse 10-byte binary payload and publish to Home Assistant MQTT sensors.
* **Home Assistant Dashboard Card:** Add custom Lovelace card for predictive outage risk gauge and grid status badge.
* **Handheld Battery Monitoring:** Add fuel gauge ADC reading and sleep mode timer to handheld firmware.
