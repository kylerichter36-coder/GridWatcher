// Auto-generated GridWatcher Random Forest ML Decision Trees
// Retrained on: 2026-08-12 17:10:02
// Train Acc: 85.83% | 80/20 Test Holdout Acc: 77.97%

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
#define ML_MODEL_VERSION 26
#endif

#ifndef ML_MODEL_BUILD_TIME
#define ML_MODEL_BUILD_TIME "2026-08-12 17:10:02"
#endif

#ifndef ML_MODEL_ACCURACY
#define ML_MODEL_ACCURACY "Train 85.8% | Test 78.0%"
#endif

inline float tree0(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (f_std_30s <= 2.2263f) {
    if (dF_dt_10s <= 0.4125f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= 0.1258f) {
          return 0.8662f;
        } else {
          return 0.7980f;
        }
      }
    } else {
      if (frequency <= 50.5050f) {
        if (frequency <= 49.4900f) {
          return 0.0000f;
        } else {
          return 0.9888f;
        }
      } else {
        return 0.0000f;
      }
    }
  } else {
    if (dF_dt_10s <= 0.4675f) {
      if (frequency <= 50.5050f) {
        if (v_slope_30s <= 0.1660f) {
          return 0.8374f;
        } else {
          return 0.6960f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (dF_dt_10s <= 0.8375f) {
        if (v_slope_30s <= 0.0635f) {
          return 0.2906f;
        } else {
          return 0.1986f;
        }
      } else {
        if (v_slope_30s <= -0.0205f) {
          return 0.0295f;
        } else {
          return 0.0494f;
        }
      }
    }
  }
}

inline float tree1(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (v_slope_30s <= 0.0804f) {
    if (dF_dt_10s <= 0.3775f) {
      if (voltage <= 209.9500f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= -0.1631f) {
          return 0.8251f;
        } else {
          return 0.7652f;
        }
      }
    } else {
      if (dV_dt_10s <= -2.4750f) {
        if (frequency <= 50.5000f) {
          return 0.9613f;
        } else {
          return 0.0000f;
        }
      } else {
        if (dV_dt_10s <= -0.4750f) {
          return 0.1123f;
        } else {
          return 0.0452f;
        }
      }
    }
  } else {
    if (voltage <= 227.8500f) {
      if (frequency <= 50.5050f) {
        if (dF_dt_10s <= -0.1625f) {
          return 0.7992f;
        } else {
          return 0.9480f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (v_slope_30s <= 0.2121f) {
        if (frequency <= 50.5050f) {
          return 0.5887f;
        } else {
          return 0.0000f;
        }
      } else {
        if (dV_dt_10s <= 0.5923f) {
          return 0.5000f;
        } else {
          return 0.2210f;
        }
      }
    }
  }
}

inline float tree2(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (dF_dt_10s <= 0.4175f) {
    if (v_std_30s <= 5.3463f) {
      if (f_std_30s <= 0.0465f) {
        return 0.0000f;
      } else {
        if (voltage <= 228.0500f) {
          return 0.8003f;
        } else {
          return 0.5339f;
        }
      }
    } else {
      if (frequency <= 50.5050f) {
        if (v_slope_30s <= 0.1168f) {
          return 0.8339f;
        } else {
          return 0.7040f;
        }
      } else {
        return 0.0000f;
      }
    }
  } else {
    if (voltage <= 228.6500f) {
      if (f_std_30s <= 1.5292f) {
        if (frequency <= 50.5050f) {
          return 0.9934f;
        } else {
          return 0.0000f;
        }
      } else {
        if (frequency <= 50.5050f) {
          return 0.9327f;
        } else {
          return 0.0000f;
        }
      }
    } else {
      if (dV_dt_10s <= -4.7250f) {
        if (f_std_30s <= 1.3817f) {
          return 0.0000f;
        } else {
          return 0.7778f;
        }
      } else {
        if (frequency <= 50.5050f) {
          return 0.9065f;
        } else {
          return 0.0000f;
        }
      }
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
