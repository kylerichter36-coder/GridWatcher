// Generated from common/features.yaml via windows_trainer/codegen.py
#ifndef FEATURES_GEN_H
#define FEATURES_GEN_H

#include <stdint.h>

#define GW_SCHEMA_VERSION   3U
#define GW_MODEL_MAGIC      0x47574D33UL
#define GW_FEATURE_HASH     0xB7DCECA1UL
#define GW_NUM_FEATURES     10U

enum GridFeatureIndex : uint8_t {
    FEAT_V_RMS = 0,
    FEAT_V_DELTA_BASELINE = 1,
    FEAT_F_HZ = 2,
    FEAT_F_CYCLE_JITTER = 3,
    FEAT_DV_DT_10S = 4,
    FEAT_DF_DT_10S = 5,
    FEAT_V_STD_30S = 6,
    FEAT_F_STD_30S = 7,
    FEAT_V_SLOPE_30S = 8,
    FEAT_F_SLOPE_30S = 9,
    FEAT_COUNT = 10
};

static const char* const GW_FEATURE_NAMES[GW_NUM_FEATURES] = {
    "v_rms",
    "v_delta_baseline",
    "f_hz",
    "f_cycle_jitter",
    "dV_dt_10s",
    "dF_dt_10s",
    "v_std_30s",
    "f_std_30s",
    "v_slope_30s",
    "f_slope_30s"
};

static const float GW_FEATURE_DEFAULTS[GW_NUM_FEATURES] = {
    230.0000f, 0.0000f, 50.0000f, 5.0000f, 0.0000f, 0.0000f, 0.2500f, 0.0200f, 0.0000f, 0.0000f
};

struct GridFeatureVector {
    union {
        float values[GW_NUM_FEATURES];
        struct {
            float v_rms;
            float v_delta_baseline;
            float f_hz;
            float f_cycle_jitter;
            float dV_dt_10s;
            float dF_dt_10s;
            float v_std_30s;
            float f_std_30s;
            float v_slope_30s;
            float f_slope_30s;
        };
    };
};

#endif // FEATURES_GEN_H
