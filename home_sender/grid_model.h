// Auto-generated GridWatcher Random Forest ML Decision Trees
// Retrained on: 2026-08-16 21:10:49
// Train Acc: 84.85% | 80/20 Test Holdout Acc: 84.56%

#ifndef GRID_MODEL_H
#define GRID_MODEL_H

#include <Arduino.h>

enum GridStatus : uint8_t {
    GRID_STATUS_NORMAL       = 0,
    GRID_STATUS_BLACKOUT     = 1,
    GRID_STATUS_BROWNOUT_SAG = 2,
    GRID_STATUS_SURGE        = 3,
    GRID_STATUS_FREQ_JITTER  = 4
};

#ifndef ML_MODEL_VERSION
#define ML_MODEL_VERSION 34
#endif

#ifndef ML_MODEL_BUILD_TIME
#define ML_MODEL_BUILD_TIME "2026-08-16 21:10:49"
#endif

#ifndef ML_MODEL_ACCURACY
#define ML_MODEL_ACCURACY "Train 84.9% | Test 84.6%"
#endif

inline float tree0(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (f_std_30s <= 1.8176f) {
    if (dF_dt_10s <= 0.0757f) {
      if (frequency <= 50.5050f) {
        return 0.8451f;
      } else {
        return 0.0000f;
      }
    } else {
      if (v_std_30s <= 3.2790f) {
        return 0.0998f;
      } else {
        return 0.1336f;
      }
    }
  } else {
    if (frequency <= 50.5050f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        return 0.9676f;
      }
    } else {
      return 0.0000f;
    }
  }
}

inline float tree1(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (v_slope_30s <= 0.0430f) {
    if (dF_dt_10s <= 0.0710f) {
      if (voltage <= 209.9500f) {
        return 0.0000f;
      } else {
        return 0.7717f;
      }
    } else {
      if (v_slope_30s <= -0.0086f) {
        return 0.1215f;
      } else {
        return 0.1122f;
      }
    }
  } else {
    if (dV_dt_10s <= 0.2422f) {
      if (frequency <= 50.5050f) {
        return 0.8734f;
      } else {
        return 0.0000f;
      }
    } else {
      if (dV_dt_10s <= 0.7618f) {
        return 0.4203f;
      } else {
        return 0.2914f;
      }
    }
  }
}

inline float tree2(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (dF_dt_10s <= 0.0752f) {
    if (v_std_30s <= 3.6965f) {
      if (f_std_30s <= 0.0350f) {
        return 0.0260f;
      } else {
        return 0.7395f;
      }
    } else {
      if (voltage <= 209.9500f) {
        return 0.0000f;
      } else {
        return 0.7328f;
      }
    }
  } else {
    if (frequency <= 50.5050f) {
      if (v_slope_30s <= 0.4177f) {
        return 0.9369f;
      } else {
        return 0.4706f;
      }
    } else {
      return 0.0000f;
    }
  }
}

inline float predictGridRisk(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
    float p0 = tree0(voltage, frequency, signal, dV_dt_10s, dF_dt_10s, v_std_30s, f_std_30s, v_slope_30s);
    float p1 = tree1(voltage, frequency, signal, dV_dt_10s, dF_dt_10s, v_std_30s, f_std_30s, v_slope_30s);
    float p2 = tree2(voltage, frequency, signal, dV_dt_10s, dF_dt_10s, v_std_30s, f_std_30s, v_slope_30s);
    float avgProb = (p0 + p1 + p2) / 3.0f;
    return avgProb * 100.0f;
}

#endif // GRID_MODEL_H
