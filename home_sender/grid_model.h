// Auto-generated GridWatcher Random Forest ML Decision Trees
// Retrained on: 2026-08-12 18:23:21
// Train Acc: 86.48% | 80/20 Test Holdout Acc: 82.75%

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
#define ML_MODEL_VERSION 31
#endif

#ifndef ML_MODEL_BUILD_TIME
#define ML_MODEL_BUILD_TIME "2026-08-12 18:23:21"
#endif

#ifndef ML_MODEL_ACCURACY
#define ML_MODEL_ACCURACY "Train 86.5% | Test 82.7%"
#endif

inline float tree0(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (f_std_30s <= 1.8529f) {
    if (dF_dt_10s <= 0.0745f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= 0.1548f) {
          return 0.8763f;
        } else {
          return 0.8100f;
        }
      }
    } else {
      if (frequency <= 50.5050f) {
        if (frequency <= 49.5000f) {
          return 0.0000f;
        } else {
          return 0.9689f;
        }
      } else {
        return 0.0000f;
      }
    }
  } else {
    if (dF_dt_10s <= 0.0812f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= 0.0637f) {
          return 0.8453f;
        } else {
          return 0.7888f;
        }
      }
    } else {
      if (dF_dt_10s <= 0.1545f) {
        if (v_slope_30s <= 0.0976f) {
          return 0.2930f;
        } else {
          return 0.2184f;
        }
      } else {
        if (v_std_30s <= 46.0638f) {
          return 0.0458f;
        } else {
          return 0.5455f;
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
          return 0.7317f;
        }
      }
    } else {
      if (dV_dt_10s <= -0.6150f) {
        if (frequency <= 50.5050f) {
          return 0.9302f;
        } else {
          return 0.0000f;
        }
      } else {
        if (dV_dt_10s <= -0.2550f) {
          return 0.1389f;
        } else {
          return 0.0378f;
        }
      }
    }
  } else {
    if (voltage <= 227.8500f) {
      if (frequency <= 50.5050f) {
        if (dF_dt_10s <= -0.0315f) {
          return 0.7925f;
        } else {
          return 0.9450f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (v_slope_30s <= 0.2121f) {
        if (frequency <= 50.5050f) {
          return 0.5893f;
        } else {
          return 0.0000f;
        }
      } else {
        if (dV_dt_10s <= 0.2764f) {
          return 0.3898f;
        } else {
          return 0.2279f;
        }
      }
    }
  }
}

inline float tree2(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (dF_dt_10s <= 0.0786f) {
    if (v_std_30s <= 4.6812f) {
      if (f_std_30s <= 0.0350f) {
        return 0.0000f;
      } else {
        if (voltage <= 209.9500f) {
          return 0.0000f;
        } else {
          return 0.7878f;
        }
      }
    } else {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= 0.0444f) {
          return 0.8519f;
        } else {
          return 0.7988f;
        }
      }
    }
  } else {
    if (voltage <= 223.9500f) {
      if (f_std_30s <= 0.4972f) {
        if (frequency <= 50.4300f) {
          return 1.0000f;
        } else {
          return 0.0000f;
        }
      } else {
        if (frequency <= 50.5050f) {
          return 0.9080f;
        } else {
          return 0.0000f;
        }
      }
    } else {
      if (dV_dt_10s <= -0.2550f) {
        if (f_std_30s <= 1.5852f) {
          return 0.3586f;
        } else {
          return 0.1969f;
        }
      } else {
        if (frequency <= 50.5050f) {
          return 0.9354f;
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
