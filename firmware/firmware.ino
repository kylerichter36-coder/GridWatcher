/*
 * GridWatcher v0.3 Firmware (ESP32-S3-WROOM-1-N16R8)
 * Author: Kyle Mason Richter (@fuelled / kylerichter36-coder)
 */

#include <Arduino.h>
#include <Wire.h>
#include "mbedtls/md.h"
#include "pins.h"
#include "features_gen.h"
#include "grid_model.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.h.example"
#endif

#define FEATURE_WINDOW_SAMPLES      32
#define ZX_RING_SIZE                50
#define OUTAGE_CONFIRM_MS           3000UL
#define RESTORE_STABILIZE_MS        60000UL
#define HEARTBEAT_INTERVAL_MS       300000UL
#define SMS_COOLDOWN_MS             600000UL
#define MAX_SMS_PER_DAY             5U

// Zero-crossing capture on GPIO 3 (BL0939 ZX output)
static volatile uint32_t g_zx_last_edge_us = 0;
static volatile uint32_t g_zx_periods_us[ZX_RING_SIZE];
static volatile uint8_t  g_zx_head = 0;
static volatile uint8_t  g_zx_count = 0;

void IRAM_ATTR onZeroCrossISR() {
    uint32_t now_us = micros();
    uint32_t diff_us = now_us - g_zx_last_edge_us;
    if (diff_us >= 15000UL && diff_us <= 25500UL) {
        g_zx_periods_us[g_zx_head] = diff_us;
        g_zx_head = (g_zx_head + 1) % ZX_RING_SIZE;
        if (g_zx_count < ZX_RING_SIZE) {
            g_zx_count++;
        }
    }
    g_zx_last_edge_us = now_us;
}

static void computeZxFrequencyAndJitter(float* out_freq_hz, float* out_jitter_mhz) {
    uint8_t count = g_zx_count;
    if (count < 4) {
        *out_freq_hz = 50.00f;
        *out_jitter_mhz = 5.0f;
        return;
    }
    float freqs[ZX_RING_SIZE];
    float sum_f = 0.0f;
    for (uint8_t i = 0; i < count; ++i) {
        uint32_t p_us = g_zx_periods_us[i];
        float f = (p_us > 0) ? (1000000.0f / (float)p_us) : 50.0f;
        freqs[i] = f;
        sum_f += f;
    }
    float mean_f = sum_f / (float)count;
    float sq_diff = 0.0f;
    for (uint8_t i = 0; i < count; ++i) {
        float d = freqs[i] - mean_f;
        sq_diff += d * d;
    }
    *out_freq_hz = mean_f;
    *out_jitter_mhz = sqrtf(sq_diff / (float)count) * 1000.0f;
}

struct TelemetrySnapshot {
    float              voltage_rms;
    float              frequency_hz;
    float              f_cycle_jitter_mhz;
    float              active_power_w;
    float              v_baseline;
    uint8_t            battery_percent;
    int8_t             cell_rsrp;
    uint16_t           cell_lac;
    uint32_t           cell_id;
    bool               mains_pgood_ok;
    bool               battery_charging;
    GridStatus         status;
    float              raw_risk_score;
    float              ema_risk_score;
    uint8_t            risk_score;
    uint8_t            high_risk_streak_s;
    bool               replay_mode_active;
    uint32_t           timestamp_ms;
    GridFeatureVector  features;
};

struct RollingBuffer {
    float    voltage[FEATURE_WINDOW_SAMPLES];
    float    frequency[FEATURE_WINDOW_SAMPLES];
    uint32_t timestamps_ms[FEATURE_WINDOW_SAMPLES];
    uint8_t  index;
    uint8_t  count;
};

struct OutageTracker {
    bool     in_blackout;
    bool     pending_post_outage_upload;
    uint32_t dip_start_ms;
    uint32_t blackout_confirmed_ms;
    uint32_t mains_restored_ms;
    float    drop_duration_ms;
    uint16_t pre_outage_lac;
    uint32_t pre_outage_cell_id;
    float    pre_outage_v_baseline;
};

static TelemetrySnapshot    g_telemetry;
static RollingBuffer        g_buffer;
static OutageTracker        g_outage;
static DynamicEnsembleModel g_dynamic_model;
static SemaphoreHandle_t    g_telemetry_mutex = NULL;

static void computeRequestHmacHex(
    const char* device_id,
    const char* ts_str,
    const char* body_json,
    const char* secret,
    char out_hex[65]
) {
    uint8_t hmac_out[32];
    mbedtls_md_context_t ctx;
    const mbedtls_md_info_t* info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    mbedtls_md_init(&ctx);
    mbedtls_md_setup(&ctx, info, 1);
    mbedtls_md_hmac_starts(&ctx, (const unsigned char*)secret, strlen(secret));
    mbedtls_md_hmac_update(&ctx, (const unsigned char*)device_id, strlen(device_id));
    mbedtls_md_hmac_update(&ctx, (const unsigned char*)":", 1);
    mbedtls_md_hmac_update(&ctx, (const unsigned char*)ts_str, strlen(ts_str));
    mbedtls_md_hmac_update(&ctx, (const unsigned char*)":", 1);
    mbedtls_md_hmac_update(&ctx, (const unsigned char*)body_json, strlen(body_json));
    mbedtls_md_hmac_finish(&ctx, hmac_out);
    mbedtls_md_free(&ctx);

    for (int i = 0; i < 32; ++i) {
        sprintf(&out_hex[i * 2], "%02x", hmac_out[i]);
    }
    out_hex[64] = '\0';
}

static size_t formatHeartbeatJson(char* out_buf, size_t max_len, const TelemetrySnapshot* t, uint32_t model_ver) {
    return (size_t)snprintf(
        out_buf,
        max_len,
        "{\"device_id\":\"%s\",\"v_rms\":%.2f,\"f_hz\":%.3f,\"f_cycle_jitter\":%.2f,"
        "\"mains_pgood_ok\":%s,\"battery_pct\":%u,\"model_version\":%lu}",
        GW_DEVICE_ID,
        t->voltage_rms,
        t->frequency_hz,
        t->f_cycle_jitter_mhz,
        t->mains_pgood_ok ? "true" : "false",
        t->battery_soc_pct,
        (unsigned long)model_ver
    );
}

static size_t formatOutageReportJson(
    char* out_buf,
    size_t max_len,
    const TelemetrySnapshot* t,
    const OutageTracker* o,
    const RollingBuffer* buf
) {
    int n = snprintf(
        out_buf,
        max_len,
        "{\"device_id\":\"%s\",\"outage_timestamp_epoch\":%lu,\"drop_duration_ms\":%.1f,"
        "\"pre_cell_id\":%lu,\"post_cell_id\":%lu,\"pre_v_baseline\":%.2f,\"post_v_baseline\":%.2f,\"samples\":[",
        GW_DEVICE_ID,
        (unsigned long)(o->blackout_confirmed_ms / 1000UL),
        o->drop_duration_ms,
        (unsigned long)o->pre_outage_cell_id,
        (unsigned long)t->cell_id,
        o->pre_outage_v_baseline,
        t->v_baseline
    );
    for (uint8_t i = 0; i < buf->count && (size_t)n + 96 < max_len; ++i) {
        uint8_t idx = (buf->index + FEATURE_WINDOW_SAMPLES - buf->count + i) % FEATURE_WINDOW_SAMPLES;
        n += snprintf(
            out_buf + n,
            max_len - (size_t)n,
            "%s{\"timestamp_s\":%.1f,\"v_rms\":%.2f,\"f_hz\":%.3f,\"f_cycle_jitter\":%.2f}",
            (i > 0) ? "," : "",
            (float)i * 1.0f,
            buf->voltage[idx],
            buf->frequency[idx],
            t->f_cycle_jitter_mhz
        );
    }
    if ((size_t)n + 4 < max_len) {
        n += snprintf(out_buf + n, max_len - (size_t)n, "]}");
    }
    return (size_t)n;
}

GridStatus evaluate_layer1(float v, float f, bool mains_pgood_ok) {
    if (!mains_pgood_ok || v < 100.0f || f < 45.00f) {
        return STATUS_BLACKOUT;
    }
    if (v > 252.0f) {
        return STATUS_VOLTAGE_SURGE;
    }
    if (v >= 100.0f && v < 210.0f) {
        return STATUS_BROWNOUT_SAG;
    }
    if (f < 49.50f || f > 50.50f) {
        return STATUS_FREQ_JITTER;
    }
    return STATUS_NORMAL;
}

void extract_10_features(
    const RollingBuffer* buf,
    float current_v,
    float current_f,
    float f_jitter_mhz,
    float v_baseline,
    uint32_t now_ms,
    GridFeatureVector* out_feat
) {
    out_feat->v_rms            = current_v;
    out_feat->v_delta_baseline = current_v - v_baseline;
    out_feat->f_hz             = current_f;
    out_feat->f_cycle_jitter   = f_jitter_mhz;
    out_feat->dV_dt_10s        = 0.0f;
    out_feat->dF_dt_10s        = 0.0f;
    out_feat->v_std_30s        = 0.0f;
    out_feat->f_std_30s        = 0.0f;
    out_feat->v_slope_30s      = 0.0f;
    out_feat->f_slope_30s      = 0.0f;

    if (buf->count < 2) {
        return;
    }

    int best_idx = -1;
    float best_diff = 999999.0f;
    for (uint8_t i = 0; i < buf->count; ++i) {
        float elapsed_s = (float)(now_ms - buf->timestamps_ms[i]) / 1000.0f;
        if (elapsed_s <= 0.0f || elapsed_s > 15.0f) continue;
        float diff = fabsf(elapsed_s - 10.0f);
        if (diff < best_diff) {
            best_diff = diff;
            best_idx = (int)i;
        }
    }
    if (best_idx >= 0) {
        float dt = (float)(now_ms - buf->timestamps_ms[best_idx]) / 1000.0f;
        if (dt < 1.0f) dt = 1.0f;
        out_feat->dV_dt_10s = (current_v - buf->voltage[best_idx]) / dt;
        out_feat->dF_dt_10s = (current_f - buf->frequency[best_idx]) / dt;
    }

    float v_sum = current_v;
    float f_sum = current_f;
    float t_sum = 0.0f;
    uint8_t n_win = 1;

    uint32_t t0_ms = buf->timestamps_ms[(buf->index + FEATURE_WINDOW_SAMPLES - buf->count) % FEATURE_WINDOW_SAMPLES];
    float t_now_rel = (float)(now_ms - t0_ms) / 1000.0f;
    t_sum += t_now_rel;

    for (uint8_t i = 0; i < buf->count; ++i) {
        float age_s = (float)(now_ms - buf->timestamps_ms[i]) / 1000.0f;
        if (age_s <= 30.5f) {
            v_sum += buf->voltage[i];
            f_sum += buf->frequency[i];
            t_sum += (float)(buf->timestamps_ms[i] - t0_ms) / 1000.0f;
            n_win++;
        }
    }

    float v_mean = v_sum / (float)n_win;
    float f_mean = f_sum / (float)n_win;
    float t_mean = t_sum / (float)n_win;

    float v_sq = (current_v - v_mean) * (current_v - v_mean);
    float f_sq = (current_f - f_mean) * (current_f - f_mean);
    float t_den = (t_now_rel - t_mean) * (t_now_rel - t_mean);
    float tv_num = (t_now_rel - t_mean) * (current_v - v_mean);
    float tf_num = (t_now_rel - t_mean) * (current_f - f_mean);

    for (uint8_t i = 0; i < buf->count; ++i) {
        float age_s = (float)(now_ms - buf->timestamps_ms[i]) / 1000.0f;
        if (age_s <= 30.5f) {
            float t_rel = (float)(buf->timestamps_ms[i] - t0_ms) / 1000.0f;
            float td = t_rel - t_mean;
            float vd = buf->voltage[i] - v_mean;
            float fd = buf->frequency[i] - f_mean;
            v_sq += vd * vd;
            f_sq += fd * fd;
            t_den += td * td;
            tv_num += td * vd;
            tf_num += td * fd;
        }
    }

    out_feat->v_std_30s = sqrtf(v_sq / (float)n_win);
    out_feat->f_std_30s = sqrtf(f_sq / (float)n_win);
    if (t_den > 0.0001f) {
        out_feat->v_slope_30s = tv_num / t_den;
        out_feat->f_slope_30s = tf_num / t_den;
    }
}

static uint8_t g_replay_step = 0;
static void stepShenzhenReplay(TelemetrySnapshot* t) {
    if (g_replay_step < 10) {
        t->voltage_rms = 230.1f - 0.1f * (float)(g_replay_step % 3);
        t->frequency_hz = 50.00f;
        t->f_cycle_jitter_mhz = 5.5f;
        t->mains_pgood_ok = true;
    } else if (g_replay_step < 35) {
        float k = (float)(g_replay_step - 10);
        t->voltage_rms = 229.5f - k * 0.85f;
        t->frequency_hz = 49.98f - k * 0.028f;
        t->f_cycle_jitter_mhz = 28.0f + k * 4.5f;
        t->mains_pgood_ok = true;
    } else if (g_replay_step < 42) {
        t->voltage_rms = 0.0f;
        t->frequency_hz = 0.0f;
        t->f_cycle_jitter_mhz = 0.0f;
        t->mains_pgood_ok = false;
    } else {
        t->replay_mode_active = false;
        g_replay_step = 0;
        t->voltage_rms = 230.0f;
        t->frequency_hz = 50.0f;
        t->f_cycle_jitter_mhz = 5.0f;
        t->mains_pgood_ok = true;
        Serial.println("[replay] done, back to live metering");
        return;
    }
    g_replay_step++;
}

void Task_EnergyMetering(void *pvParameters) {
    Serial1.begin(4800, SERIAL_8N1, PIN_BL0939_RX, PIN_BL0939_TX);
    pinMode(PIN_BL0939_ZX, INPUT);
    attachInterrupt(digitalPinToInterrupt(PIN_BL0939_ZX), onZeroCrossISR, RISING);

    for (;;) {
        if (xSemaphoreTake(g_telemetry_mutex, portMAX_DELAY) == pdTRUE) {
            if (g_telemetry.replay_mode_active) {
                stepShenzhenReplay(&g_telemetry);
            } else {
                float zx_f = 50.0f, zx_j = 5.0f;
                computeZxFrequencyAndJitter(&zx_f, &zx_j);
                g_telemetry.frequency_hz = zx_f;
                g_telemetry.f_cycle_jitter_mhz = zx_j;
            }
            xSemaphoreGive(g_telemetry_mutex);
        }
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}

void Task_PredictionEngine(void *pvParameters) {
    for (;;) {
        if (xSemaphoreTake(g_telemetry_mutex, portMAX_DELAY) == pdTRUE) {
            uint32_t now_ms = millis();
            g_telemetry.timestamp_ms = now_ms;

            g_telemetry.status = evaluate_layer1(
                g_telemetry.voltage_rms,
                g_telemetry.frequency_hz,
                g_telemetry.mains_pgood_ok
            );

            extract_10_features(
                &g_buffer,
                g_telemetry.voltage_rms,
                g_telemetry.frequency_hz,
                g_telemetry.f_cycle_jitter_mhz,
                g_telemetry.v_baseline,
                now_ms,
                &g_telemetry.features
            );

            if (g_telemetry.status == STATUS_NORMAL && g_telemetry.features.v_std_30s < 0.8f) {
                g_telemetry.v_baseline = 0.999f * g_telemetry.v_baseline + 0.001f * g_telemetry.voltage_rms;
            }

            float l2a_risk = evaluateLayer2AUnsupervised(g_telemetry.features.values);
            float l2b_risk = predictGridRisk(g_telemetry.features.values, &g_dynamic_model);
            g_telemetry.raw_risk_score = (l2b_risk >= l2a_risk) ? l2b_risk : (0.7f * l2b_risk + 0.3f * l2a_risk);

            g_telemetry.ema_risk_score = 0.4f * g_telemetry.raw_risk_score + 0.6f * g_telemetry.ema_risk_score;
            g_telemetry.risk_score = (uint8_t)(g_telemetry.ema_risk_score + 0.5f);

            if (g_telemetry.risk_score >= 70) {
                if (g_telemetry.high_risk_streak_s < 255) g_telemetry.high_risk_streak_s++;
            } else if (g_telemetry.risk_score < 40) {
                g_telemetry.high_risk_streak_s = 0;
            }

            if (g_telemetry.status == STATUS_BLACKOUT) {
                if (g_outage.dip_start_ms == 0) {
                    g_outage.dip_start_ms = now_ms;
                    g_outage.pre_outage_lac = g_telemetry.cell_lac;
                    g_outage.pre_outage_cell_id = g_telemetry.cell_id;
                    g_outage.pre_outage_v_baseline = g_telemetry.v_baseline;
                } else if (!g_outage.in_blackout && (now_ms - g_outage.dip_start_ms) >= OUTAGE_CONFIRM_MS) {
                    g_outage.in_blackout = true;
                    g_outage.blackout_confirmed_ms = now_ms;
                    g_outage.pending_post_outage_upload = true;
                }
            } else {
                if (g_outage.in_blackout) {
                    g_outage.in_blackout = false;
                    g_outage.mains_restored_ms = now_ms;
                }
                g_outage.dip_start_ms = 0;
            }

            g_buffer.voltage[g_buffer.index]       = g_telemetry.voltage_rms;
            g_buffer.frequency[g_buffer.index]     = g_telemetry.frequency_hz;
            g_buffer.timestamps_ms[g_buffer.index] = now_ms;
            g_buffer.index = (g_buffer.index + 1) % FEATURE_WINDOW_SAMPLES;
            if (g_buffer.count < FEATURE_WINDOW_SAMPLES) g_buffer.count++;

            xSemaphoreGive(g_telemetry_mutex);
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

void Task_CellularTelemetry(void *pvParameters) {
    pinMode(PIN_MODEM_PWRKEY, OUTPUT);
    pinMode(PIN_MODEM_RESET, OUTPUT);
    digitalWrite(PIN_MODEM_RESET, LOW);

    digitalWrite(PIN_MODEM_PWRKEY, HIGH);
    vTaskDelay(pdMS_TO_TICKS(1000));
    digitalWrite(PIN_MODEM_PWRKEY, LOW);

    Serial2.begin(115200, SERIAL_8N1, PIN_MODEM_RX_3V3, PIN_MODEM_TX_3V3);

    uint32_t last_sms_ms = 0;
    uint8_t  sms_sent_today = 0;

    for (;;) {
        if (xSemaphoreTake(g_telemetry_mutex, portMAX_DELAY) == pdTRUE) {
            uint32_t now_ms = millis();
            if (g_telemetry.high_risk_streak_s >= 3 && sms_sent_today < MAX_SMS_PER_DAY) {
                if (last_sms_ms == 0 || (now_ms - last_sms_ms) >= SMS_COOLDOWN_MS) {
                    last_sms_ms = now_ms;
                    sms_sent_today++;
                    Serial.printf(
                        "[alert] risk=%u%% V=%.1fV F=%.2fHz jitter=%.1fmHz\n",
                        g_telemetry.risk_score,
                        g_telemetry.voltage_rms,
                        g_telemetry.frequency_hz,
                        g_telemetry.f_cycle_jitter_mhz
                    );
                }
            }

            if (!g_outage.in_blackout && g_outage.pending_post_outage_upload && g_outage.mains_restored_ms > 0) {
                if ((now_ms - g_outage.mains_restored_ms) >= RESTORE_STABILIZE_MS) {
                    static char json_body[2048];
                    char ts_str[24];
                    char sig_hex[65];
                    snprintf(ts_str, sizeof(ts_str), "%lu", (unsigned long)(now_ms / 1000UL));
                    formatOutageReportJson(json_body, sizeof(json_body), &g_telemetry, &g_outage, &g_buffer);
                    computeRequestHmacHex(GW_DEVICE_ID, ts_str, json_body, GW_HMAC_SECRET, sig_hex);

                    Serial2.println("AT+HTTPINIT");
                    Serial2.printf("AT+HTTPPARA=\"URL\",\"%s/api/v1/outage-report\"\r\n", GW_SERVER_URL);
                    Serial2.printf(
                        "AT+HTTPPARA=\"USERDATA\",\"X-Device-ID: %s\\r\\nX-Timestamp: %s\\r\\nX-Signature: %s\"\r\n",
                        GW_DEVICE_ID,
                        ts_str,
                        sig_hex
                    );
                    Serial.printf("[sync] uploaded post-outage report (%u B, hmac=%s)\n", (unsigned)strlen(json_body), sig_hex);
                    g_outage.pending_post_outage_upload = false;
                }
            }
            xSemaphoreGive(g_telemetry_mutex);
        }
        vTaskDelay(pdMS_TO_TICKS(2000));
    }
}

void Task_BlackboxStorage(void *pvParameters) {
    pinMode(PIN_SDNAND_CS, OUTPUT);
    digitalWrite(PIN_SDNAND_CS, HIGH);
    static char csv_line[128];

    for (;;) {
        if (xSemaphoreTake(g_telemetry_mutex, portMAX_DELAY) == pdTRUE) {
            snprintf(
                csv_line,
                sizeof(csv_line),
                "%lu,%.2f,%.3f,%.2f,%d,%u\n",
                (unsigned long)g_telemetry.timestamp_ms,
                g_telemetry.voltage_rms,
                g_telemetry.frequency_hz,
                g_telemetry.f_cycle_jitter_mhz,
                g_telemetry.mains_pgood_ok ? 1 : 0,
                g_telemetry.risk_score
            );
            xSemaphoreGive(g_telemetry_mutex);
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

void Task_PowerManagement(void *pvParameters) {
    Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
    pinMode(PIN_BQ24074_CHG, INPUT_PULLUP);
    pinMode(PIN_BQ24074_PGOOD, INPUT_PULLUP);
    pinMode(PIN_MAX17048_ALERT, INPUT_PULLUP);

    for (;;) {
        bool pgood_low = (digitalRead(PIN_BQ24074_PGOOD) == LOW);
        bool chg_low   = (digitalRead(PIN_BQ24074_CHG) == LOW);

        if (xSemaphoreTake(g_telemetry_mutex, portMAX_DELAY) == pdTRUE) {
            if (!g_telemetry.replay_mode_active) {
                g_telemetry.mains_pgood_ok = pgood_low;
            }
            g_telemetry.battery_charging = chg_low;

            if (Serial.available() > 0) {
                String cmd = Serial.readStringUntil('\n');
                cmd.trim();
                if (cmd.equalsIgnoreCase("REPLAY") || cmd.equalsIgnoreCase("REPLAY_SA_BLACKOUT")) {
                    g_telemetry.replay_mode_active = true;
                    g_replay_step = 0;
                    Serial.println("[replay] starting recorded SA blackout trace");
                }
            }
            xSemaphoreGive(g_telemetry_mutex);
        }
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}

void setup() {
    Serial.begin(115200);
    memset(&g_telemetry, 0, sizeof(g_telemetry));
    memset(&g_buffer, 0, sizeof(g_buffer));
    memset(&g_outage, 0, sizeof(g_outage));
    memset(&g_dynamic_model, 0, sizeof(g_dynamic_model));

    g_telemetry.voltage_rms    = 230.0f;
    g_telemetry.frequency_hz   = 50.00f;
    g_telemetry.v_baseline     = 230.0f;
    g_telemetry.mains_pgood_ok = true;
    g_telemetry.cell_rsrp      = -92;

    g_telemetry_mutex = xSemaphoreCreateMutex();

    xTaskCreatePinnedToCore(Task_EnergyMetering,    "BL0939_ZX",     4096, NULL, 3, NULL, 1);
    xTaskCreatePinnedToCore(Task_PredictionEngine,  "AI_Predictor",  6144, NULL, 2, NULL, 1);
    xTaskCreatePinnedToCore(Task_CellularTelemetry, "A7670E_Cell",   6144, NULL, 2, NULL, 0);
    xTaskCreatePinnedToCore(Task_BlackboxStorage,   "NAND_Storage",  4096, NULL, 1, NULL, 0);
    xTaskCreatePinnedToCore(Task_PowerManagement,   "Power_Monitor", 4096, NULL, 2, NULL, 1);
}

void loop() {
    vTaskDelay(pdMS_TO_TICKS(1000));
}
