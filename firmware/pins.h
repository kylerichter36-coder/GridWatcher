/*
 * GridWatcher v0.3 PCB pin definitions (ESP32-S3-WROOM-1-N16R8, U6)
 * Matched to Hardware/GridWatcher_v0.3/GriDwatcher china.kicad_pcb
 */

#ifndef PINS_H
#define PINS_H

// BL0939 energy metering IC (U2)
#define PIN_BL0939_RX          1   // U6 IO1 <- U2 pad 15 (TX/SDO)
#define PIN_BL0939_TX          2   // U6 IO2 -> U2 pad 14 (RX/SDI)
#define PIN_BL0939_ZX          3   // U6 IO3 <- U2 pad 9 (ZX zero-crossing output)

// BQ24074 charger/power-path (U3) & MAX17048 fuel gauge (U5)
#define PIN_BQ24074_CHG        4   // ~CHG open-drain (LOW = charging)
#define PIN_BQ24074_PGOOD      5   // ~PGOOD open-drain (LOW = AC mains present, HIGH = mains lost)
#define PIN_I2C_SDA            6   // MAX17048 SDA
#define PIN_I2C_SCL            7   // MAX17048 SCL
#define PIN_MAX17048_ALERT     8   // MAX17048 ~ALERT

// XTSDG08GWSIGA 1GB SD-NAND flash (U7, 1-bit SDMMC)
#define PIN_SDNAND_CMD        11
#define PIN_SDNAND_CLK        12   // routed through R22 (22 ohm)
#define PIN_SDNAND_DAT0       13
#define PIN_SDNAND_CS         14   // DAT3/CS (net labeled /IO10 on schematic)

// SIMCom A7670E LTE Cat-1 modem (via TXS0102 level shifter & BSS138 FETs)
#define PIN_MODEM_RESET       15   // Q2 gate
#define PIN_MODEM_PWRKEY      16   // Q1 gate
#define PIN_MODEM_TX_3V3      17   // ESP32 TX -> TXS0102 -> Modem RXD
#define PIN_MODEM_RX_3V3      18   // ESP32 RX <- TXS0102 <- Modem TXD

#endif // PINS_H
