// Auto-generated GridWatcher Random Forest ML Decision Trees
// Retrained on: 2026-08-12 17:50:33
// Train Acc: 87.15% | 80/20 Test Holdout Acc: 83.09%

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
#define ML_MODEL_VERSION 30
#endif

#ifndef ML_MODEL_BUILD_TIME
#define ML_MODEL_BUILD_TIME "2026-08-12 17:50:33"
#endif

#ifndef ML_MODEL_ACCURACY
#define ML_MODEL_ACCURACY "Train 87.2% | Test 83.1%"
#endif

inline float tree0(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (f_std_30s <= 2.0138f) {
    if (dF_dt_10s <= 0.0775f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= 0.1548f) {
          return 0.8724f;
        } else {
          return 0.7938f;
        }
      }
    } else {
      if (frequency <= 50.5050f) {
        if (frequency <= 49.5000f) {
          return 0.0000f;
        } else {
          return 0.9701f;
        }
      } else {
        return 0.0000f;
      }
    }
  } else {
    if (dF_dt_10s <= 0.0815f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= 0.0554f) {
          return 0.8452f;
        } else {
          return 0.7850f;
        }
      }
    } else {
      if (dF_dt_10s <= 0.1905f) {
        if (v_slope_30s <= 0.0961f) {
          return 0.2723f;
        } else {
          return 0.1940f;
        }
      } else {
        if (v_slope_30s <= 9.2905f) {
          return 0.0356f;
        } else {
          return 0.7143f;
        }
      }
    }
  }
}

inline float tree1(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (v_slope_30s <= 0.0804f) {
    if (dF_dt_10s <= 0.0832f) {
      if (voltage <= 209.9500f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= 0.0446f) {
          return 0.7881f;
        } else {
          return 0.7316f;
        }
      }
    } else {
      if (dV_dt_10s <= -0.6150f) {
        if (frequency <= 50.5050f) {
          return 0.9298f;
        } else {
          return 0.0000f;
        }
      } else {
        if (dV_dt_10s <= -0.2550f) {
          return 0.1341f;
        } else {
          return 0.0369f;
        }
      }
    }
  } else {
    if (voltage <= 227.8500f) {
      if (frequency <= 50.5050f) {
        if (dF_dt_10s <= -0.0315f) {
          return 0.7950f;
        } else {
          return 0.9450f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (v_slope_30s <= 0.2121f) {
        if (frequency <= 50.5050f) {
          return 0.5886f;
        } else {
          return 0.0000f;
        }
      } else {
        if (dV_dt_10s <= 0.2764f) {
          return 0.3861f;
        } else {
          return 0.2284f;
        }
      }
    }
  }
}

inline float tree2(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (dF_dt_10s <= 0.0786f) {
    if (v_std_30s <= 4.3933f) {
      if (f_std_30s <= 0.0350f) {
        return 0.0000f;
      } else {
        if (voltage <= 209.9500f) {
          return 0.0000f;
        } else {
          return 0.7937f;
        }
      }
    } else {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= 0.0444f) {
          return 0.8547f;
        } else {
          return 0.8029f;
        }
      }
    }
  } else {
    if (voltage <= 223.9500f) {
      if (f_std_30s <= 0.7197f) {
        if (frequency <= 50.5000f) {
          return 0.9744f;
        } else {
          return 0.0000f;
        }
      } else {
        if (frequency <= 50.5050f) {
          return 0.9064f;
        } else {
          return 0.0000f;
        }
      }
    } else {
      if (dV_dt_10s <= -0.2550f) {
        if (f_std_30s <= 1.5852f) {
          return 0.3586f;
        } else {
          return 0.1965f;
        }
      } else {
        if (frequency <= 50.5050f) {
          return 0.9342f;
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
