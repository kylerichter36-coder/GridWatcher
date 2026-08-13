// Auto-generated GridWatcher Random Forest ML Decision Trees
// Retrained on: 2026-08-13 18:46:45
// Train Acc: 85.29% | 80/20 Test Holdout Acc: 83.40%

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
#define ML_MODEL_VERSION 32
#endif

#ifndef ML_MODEL_BUILD_TIME
#define ML_MODEL_BUILD_TIME "2026-08-13 18:46:45"
#endif

#ifndef ML_MODEL_ACCURACY
#define ML_MODEL_ACCURACY "Train 85.3% | Test 83.4%"
#endif

inline float tree0(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (f_std_30s <= 1.8483f) {
    if (dF_dt_10s <= 0.0748f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        return 0.8421f;
      }
    } else {
      if (v_std_30s <= 2.9483f) {
        return 0.0713f;
      } else {
        return 0.1413f;
      }
    }
  } else {
    if (frequency <= 50.5050f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        return 0.9576f;
      }
    } else {
      return 0.0000f;
    }
  }
}

inline float tree1(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (v_slope_30s <= 0.0475f) {
    if (dF_dt_10s <= 0.0812f) {
      if (voltage <= 209.9500f) {
        return 0.0000f;
      } else {
        return 0.7732f;
      }
    } else {
      if (v_slope_30s <= 0.0475f) {
        return 0.0969f;
      } else {
        return 0.6667f;
      }
    }
  } else {
    if (dV_dt_10s <= 0.2789f) {
      if (frequency <= 50.5050f) {
        return 0.8663f;
      } else {
        return 0.0000f;
      }
    } else {
      if (dV_dt_10s <= 0.8725f) {
        return 0.4083f;
      } else {
        return 0.2531f;
      }
    }
  }
}

inline float tree2(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (dF_dt_10s <= 0.0775f) {
    if (v_std_30s <= 2.2962f) {
      if (f_std_30s <= 0.1141f) {
        return 0.0667f;
      } else {
        return 0.8108f;
      }
    } else {
      if (voltage <= 209.9500f) {
        return 0.0000f;
      } else {
        return 0.7465f;
      }
    }
  } else {
    if (frequency <= 50.5050f) {
      if (v_slope_30s <= 0.4373f) {
        return 0.9318f;
      } else {
        return 0.5385f;
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
