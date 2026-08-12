// Auto-generated GridWatcher Random Forest ML Decision Trees
// Retrained on: 2026-08-12 17:31:23
// Train Acc: 86.10% | 80/20 Test Holdout Acc: 77.34%

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
#define ML_MODEL_VERSION 28
#endif

#ifndef ML_MODEL_BUILD_TIME
#define ML_MODEL_BUILD_TIME "2026-08-12 17:31:23"
#endif

#ifndef ML_MODEL_ACCURACY
#define ML_MODEL_ACCURACY "Train 86.1% | Test 77.3%"
#endif

inline float tree0(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (f_std_30s <= 2.0138f) {
    if (dF_dt_10s <= 0.3775f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= 0.1548f) {
          return 0.8722f;
        } else {
          return 0.7952f;
        }
      }
    } else {
      if (frequency <= 50.5050f) {
        if (frequency <= 49.4900f) {
          return 0.0000f;
        } else {
          return 0.9876f;
        }
      } else {
        return 0.0000f;
      }
    }
  } else {
    if (dF_dt_10s <= 0.4675f) {
      if (frequency <= 50.5050f) {
        if (v_slope_30s <= 0.1590f) {
          return 0.8440f;
        } else {
          return 0.7047f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (dF_dt_10s <= 0.8725f) {
        if (v_slope_30s <= 0.0634f) {
          return 0.2783f;
        } else {
          return 0.1931f;
        }
      } else {
        if (v_std_30s <= 3.2866f) {
          return 0.0204f;
        } else {
          return 0.0435f;
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
        if (v_slope_30s <= -0.1411f) {
          return 0.8207f;
        } else {
          return 0.7646f;
        }
      }
    } else {
      if (dV_dt_10s <= -2.4750f) {
        if (frequency <= 50.5000f) {
          return 0.9619f;
        } else {
          return 0.0000f;
        }
      } else {
        if (dV_dt_10s <= -0.4750f) {
          return 0.1117f;
        } else {
          return 0.0448f;
        }
      }
    }
  } else {
    if (voltage <= 227.8500f) {
      if (frequency <= 50.5050f) {
        if (dF_dt_10s <= -0.1625f) {
          return 0.7960f;
        } else {
          return 0.9486f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (v_slope_30s <= 0.2121f) {
        if (frequency <= 50.5050f) {
          return 0.5880f;
        } else {
          return 0.0000f;
        }
      } else {
        if (dV_dt_10s <= 0.5923f) {
          return 0.5000f;
        } else {
          return 0.2216f;
        }
      }
    }
  }
}

inline float tree2(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (dF_dt_10s <= 0.4175f) {
    if (v_std_30s <= 5.1650f) {
      if (f_std_30s <= 0.0379f) {
        return 0.0000f;
      } else {
        if (voltage <= 228.0500f) {
          return 0.7982f;
        } else {
          return 0.5348f;
        }
      }
    } else {
      if (frequency <= 50.5050f) {
        if (v_slope_30s <= 0.1168f) {
          return 0.8340f;
        } else {
          return 0.7039f;
        }
      } else {
        return 0.0000f;
      }
    }
  } else {
    if (voltage <= 228.6500f) {
      if (f_std_30s <= 1.4773f) {
        if (frequency <= 50.5050f) {
          return 0.9937f;
        } else {
          return 0.0000f;
        }
      } else {
        if (frequency <= 50.5050f) {
          return 0.9336f;
        } else {
          return 0.0000f;
        }
      }
    } else {
      if (dV_dt_10s <= -4.7250f) {
        if (f_std_30s <= 1.3349f) {
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
