// Auto-generated GridWatcher Random Forest ML Decision Trees
// Retrained on: 2026-08-12 16:49:04
// Train Acc: 85.25% | 80/20 Test Holdout Acc: 84.47%

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
#define ML_MODEL_VERSION 23
#endif

#ifndef ML_MODEL_BUILD_TIME
#define ML_MODEL_BUILD_TIME "2026-08-12 16:49:04"
#endif

#ifndef ML_MODEL_ACCURACY
#define ML_MODEL_ACCURACY "Train 85.2% | Test 84.5%"
#endif

inline float tree0(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (f_std_30s <= 2.0815f) {
    if (dF_dt_10s <= 0.3775f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= 1.5417f) {
          return 0.7205f;
        } else {
          return 0.5318f;
        }
      }
    } else {
      if (frequency <= 50.5050f) {
        if (frequency <= 49.4900f) {
          return 0.0000f;
        } else {
          return 0.8210f;
        }
      } else {
        return 0.0000f;
      }
    }
  } else {
    if (dF_dt_10s <= 0.4525f) {
      if (frequency <= 50.5050f) {
        if (v_slope_30s <= 1.2417f) {
          return 0.7012f;
        } else {
          return 0.4992f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (dF_dt_10s <= 0.8725f) {
        if (v_slope_30s <= -1.2417f) {
          return 0.4807f;
        } else {
          return 0.1619f;
        }
      } else {
        if (v_slope_30s <= -0.6250f) {
          return 0.0712f;
        } else {
          return 0.0233f;
        }
      }
    }
  }
}

inline float tree1(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (v_slope_30s <= 1.3250f) {
    if (dF_dt_10s <= 0.4675f) {
      if (voltage <= 209.9500f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= -0.6845f) {
          return 0.7038f;
        } else {
          return 0.6140f;
        }
      }
    } else {
      if (dV_dt_10s <= -2.1250f) {
        if (frequency <= 50.5000f) {
          return 0.8779f;
        } else {
          return 0.0000f;
        }
      } else {
        if (dV_dt_10s <= -1.0250f) {
          return 0.0940f;
        } else {
          return 0.0246f;
        }
      }
    }
  } else {
    if (voltage <= 228.2500f) {
      if (frequency <= 50.5050f) {
        if (dF_dt_10s <= 1.5350f) {
          return 0.6884f;
        } else {
          return 0.0000f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (v_slope_30s <= 3.7083f) {
        if (frequency <= 50.5050f) {
          return 0.3909f;
        } else {
          return 0.0000f;
        }
      } else {
        if (f_std_30s <= 2.3086f) {
          return 0.3333f;
        } else {
          return 0.6087f;
        }
      }
    }
  }
}

inline float tree2(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (dF_dt_10s <= 0.4175f) {
    if (v_std_30s <= 8.6719f) {
      if (f_std_30s <= 0.1790f) {
        if (voltage <= 224.4000f) {
          return 0.0680f;
        } else {
          return 0.8571f;
        }
      } else {
        if (frequency <= 50.5050f) {
          return 0.6989f;
        } else {
          return 0.0000f;
        }
      }
    } else {
      if (v_slope_30s <= 0.4967f) {
        if (voltage <= 210.9500f) {
          return 0.0000f;
        } else {
          return 0.6782f;
        }
      } else {
        if (f_std_30s <= 26.1474f) {
          return 0.1781f;
        } else {
          return 0.5714f;
        }
      }
    }
  } else {
    if (frequency <= 50.5050f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        if (dV_dt_10s <= 5.7500f) {
          return 0.8513f;
        } else {
          return 0.3200f;
        }
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
