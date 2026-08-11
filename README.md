# GridWatcher System Architecture & Specification

GridWatcher is an off-grid electrical grid monitoring platform designed for real-time AC voltage and frequency analysis, predictive outage risk modeling, and long-range telemetric alerting.

The system combines low-latency ESP32-C6 edge hardware, SX1262 LoRa telemetry, an Armbian Linux home server running Docker Compose (Home Assistant and telemetry logger), and an automated machine learning retraining utility.

---

## Repository Components

```
GridWatcher/
├── home_sender/              # ESP32-C6 Base Station transmitter firmware
│   ├── home_sender.ino       # ZMPT101B RMS sampling, Layer 1 status, LoRa TX
│   └── grid_model.h          # Exported C++ Random Forest decision tree model
├── gridwatcher_dashboard2/   # ESP32 Handheld receiver & TFT dashboard firmware
│   └── gridwatcher_dashboard2.ino
├── windows_trainer/          # Automated Windows training pipeline & GUI
│   ├── gridwatcher_ml_gui.py # PyQt GUI, gap-aware feature extractor, C++ exporter
│   └── install_startup.bat   # 1-click dependency installer (arduino-cli standalone)
├── WORKING_ON/               # Active development status & phase documentation
│   └── README.md
└── version.json              # Current firmware & ML model version manifest
```

---

## Core Technical Design

### 1. Dual-Layer Classification Architecture
* **Layer 1: Deterministic C++ State Machine (`home_sender.ino`)**
  * Evaluates instantaneous voltage and frequency using strict severity precedence:
    1. Blackout (`V < 180.0V` or `F < 45.00Hz`)
    2. Voltage Surge (`V > 250.0V`)
    3. Brownout Sag (`180.0V <= V < 210.0V`)
    4. Frequency Jitter (`210.0V <= V <= 250.0V` and `F < 49.50Hz` or `F > 50.50Hz`)
    5. Normal (`210.0V <= V <= 250.0V` and `49.50Hz <= F <= 50.50Hz`)

* **Layer 2: Predictive Time-Series ML Risk Model (`grid_model.h`)**
  * Evaluates 5 rolling window features extracted from a 30-sample circular ring buffer:
    * `dV_dt_10s`: 10-second voltage rate of change.
    * `dF_dt_10s`: 10-second frequency rate of change.
    * `v_std_30s`: 30-second voltage standard deviation.
    * `f_std_30s`: 30-second frequency standard deviation.
    * `v_slope_30s`: 30-second linear regression voltage slope.
  * Outputs a predictive risk score from 0.0% to 100.0% using an ensemble of 3 Random Forest decision trees (`max_depth=4`) exported directly to native C++ nested conditions.

### 2. Binary LoRa Telemetry Protocol
Telemetry is packed into a 10-byte binary structure (`GridPacket`), providing a 3.4x reduction in RF airtime compared to legacy ASCII string formatting:

```cpp
struct __attribute__((packed)) GridPacket {
    uint16_t magic = 0x4757;  // 2 Bytes: 'GW' Header
    int16_t  voltage_x10;     // 2 Bytes: Scaled Voltage (2301 = 230.1V)
    uint16_t freq_x100;       // 2 Bytes: Scaled Frequency (5000 = 50.00Hz)
    uint8_t  status;          // 1 Byte: GridStatus Enum (0..4)
    uint8_t  risk_score;      // 1 Byte: Predictive Risk % (0..100)
    uint8_t  ml_version;      // 1 Byte: Model Build Version
    int8_t   rssi;            // 1 Byte: Cell Signal Strength (dBm)
};
```

Both Handheld and Server receivers validate `packet.magic == 0x4757` to reject unauthenticated packets.

---

## Machine Learning Pipeline & Training

1. Telemetry datasets are logged automatically by the Orange Pi server.
2. `gridwatcher_ml_gui.py` downloads `telemetry.csv` and computes rolling features with timestamp gap invalidation ($\Delta t > 2\text{s}$).
3. Samples are labeled with a continuous 0–30s forward-looking horizon (`target_risk = 1` if an anomaly occurs within the upcoming 30 seconds while current state is Normal).
4. Scikit-Learn fits a 3-tree Random Forest classifier and exports `tree0()`, `tree1()`, `tree2()` into `home_sender/grid_model.h`.
5. The Base Station firmware is compiled using `arduino-cli` and updated wirelessly via local HTTP OTA.

---

## Local Setup & Wi-Fi Credentials

Wi-Fi credentials are kept out of revision control:
* On the primary flashing PC, `home_sender/secrets.h` defines local network credentials.
* On secondary PCs, `secrets.h` is omitted (`#if __has_include("secrets.h")`). The firmware falls back cleanly to credentials stored in ESP32 NVS memory during initial setup.

To set up a new machine:
1. Run `windows_trainer/install_startup.bat` to install `arduino-cli`, the ESP32 board core, required libraries (`RadioLib`, `Adafruit GFX`, `ST7789`, `BusIO`), and Python dependencies.
2. Launch `windows_trainer/gridwatcher_ml_gui.py` to run retraining and automated OTA deployment.
