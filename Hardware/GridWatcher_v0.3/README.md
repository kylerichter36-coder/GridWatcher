# GridWatcher Hardware v0.3

Monolithic 2-layer integrated telemetry and energy monitoring board designed for JLCPCB SMT assembly, replacing the modular v0.2 breakout carrier board.

## Specifications

* **Board Dimensions:** 113.40 mm x 69.22 mm (2-layer FR-4, 1.6 mm thickness, 1 oz copper)
* **Microcontroller:** ESP32-S3-WROOM-1-N16R8 (16MB Flash, 8MB Octal PSRAM, 2.4 GHz Wi-Fi + BLE 5)
* **Cellular Modem:** SIMCom A7670E LTE Cat-1 LGA module with micro-strip trace to test point / external antenna, paired with a hinged 6-pin Nano-SIM socket (J2)
* **Energy Metering:** BL0939 dual-channel energy measurement IC (UART interface to ESP32-S3) + ZMPT101K voltage transformer + dual 412k 1206 voltage divider string
* **Battery & Power Path:**
  * Hi-Link HLK-10M05 isolated 10W (5V 2A) AC-DC converter for direct 100-240V AC mains operation
  * TI BQ24074 1.5A Li-ion linear charger with autonomous dynamic power-path management (SYS output prioritized over battery charging)
  * Silergy SY8089A1AAC 2A synchronous step-down buck converter (5V/VSYS -> 3.3V system rail)
  * Maxim MAX17048 I2C fuel gauge (DFN-8) for 1S battery state-of-charge tracking
* **Non-Volatile Storage:** XTX XTSDG08GWSIGA 1GB (8Gb) SD-NAND in LGA-8 package (SDIO 1-bit / 4-bit bus) for continuous electrical event recording
* **Level Translation:** TI TXS0102DCUR bidirectional voltage translator bridging 3.3V ESP32 UART logic to 1.8V A7670E cellular baseband UART

## Subsystem Pin Mapping

| ESP32-S3 Pin | Function / Net | Connected Peripheral |
| :--- | :--- | :--- |
| GPIO4 | `/ESP GPIO CHG` | BQ24074 `CHG` open-drain status |
| GPIO5 | `/ESP GPIO-` | Status LED / auxiliary GPIO |
| GPIO6 | `/ESP SDA` | MAX17048 I2C data (pulled up to 3.3V via R10) |
| GPIO7 | `/ESP SCL` | MAX17048 I2C clock (pulled up to 3.3V via R11) |
| GPIO8 | `/ESP_RESET` | A7670E `RESET` gate driver (via N-channel FET Q2) |
| GPIO9 | `/ESP_PWRKEY` | A7670E `PWRKEY` gate driver (via N-channel FET Q1) |
| GPIO10 | `/MODEM_TX_3V3` | TXS0102 Port A pin 1 (level-shifted from A7670E TXD 1.8V) |
| GPIO11 | `/MODEM_RX_3V3` | TXS0102 Port A pin 8 (level-shifted to A7670E RXD 1.8V) |
| GPIO10, 11, 12, 13 | `/IO10`, `/IO11`, `/IO12`, `/IO13` | XTX SD-NAND LGA-8 (DAT2, DAT3, CLK, CMD lines) |
| GPIO15 | `/esp32 gpio` | BL0939 CF1 / interrupt pulse output |
| GPIO19 (U0RXD) | `/RX 939` | BL0939 UART TX output (3.3V domain) |
| GPIO20 (U0TXD) | `/TX 939` | BL0939 UART RX input (3.3V domain) |
| USB D- / D+ | Direct pads | Native ESP32-S3 USB interface |

## JLCPCB SMT Production Files

All production outputs are located in this directory:

* `GriDwatcher_china_gerbers.zip`: Standard RS-274X Gerbers and Excellon drill files generated from KiCad 8. Silkscreen contains hidden `JLCJLCJLCJLC` order marker under U1 footprint.
* `jlcpcb_bom.csv`: SMT pick-and-place Bill of Materials with verified LCSC part codes.
* `jlcpcb_bom_complete.csv`: Full project BOM including hand-soldered through-hole components.
* `jlcpcb_cpl.csv`: Centroid placement file with component rotations mapped for JLCPCB automated feeders.
* `GriDwatcher_china_v0.3.step`: Complete 3D mechanical assembly model (OpenCASCADE AP214 format).

### Component Sourcing & Errata

1. **Through-Hole Parts (Manual Post-Assembly):**
   * `U1`: Hi-Link HLK-10M05 isolated AC-DC module
   * `TR1`: ZMPT101K voltage transformer
   * `RV1`: 10D471K 275VAC metal oxide varistor
   * `F1`: 5x20 mm PCB fuse clips
   * `J1`: JST-PH 2.0 mm right-angle 2-pin connector
2. **SMT Pick-and-Place Feeder Codes:**
   * `Q1, Q2`: SOT-23 N-channel MOSFETs (`C52895` onsemi BSS138).
   * `J2`: Hinged Nano-SIM 6-pin socket (`C2963104` BOOMELE NANO SIM 6PIN).
   * `L1`: 10uH shielded power inductor 7.3x7.3 mm (`C915310` MetalLions MSRH74-100MT).
   * `C19`: 470uF 6.3V Case D 7343 low-ESR tantalum capacitor (`C7229`).
   * `U4`: SOT-23-5 buck regulator requires 180° rotation offset in CPL relative to KiCad standard orientation.
   * `C2`: 100uF 25V 6.3x7.7 mm SMD aluminum electrolytic requires 0° CPL orientation to align cathode with GND pad.
3. **Do Not Populate (DNP):**
   * `C24`, `C25`: RF tuning pads near SIM socket reserved for impedance matching on custom antenna geometries.
