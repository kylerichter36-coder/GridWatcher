// Auto-generated GridWatcher Random Forest ML Decision Trees
// Retrained on: 2026-08-12 16:38:37
// Train Acc: 86.21% | 80/20 Test Holdout Acc: 85.10%

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
#define ML_MODEL_VERSION 22
#endif

#ifndef ML_MODEL_BUILD_TIME
#define ML_MODEL_BUILD_TIME "2026-08-12 16:38:37"
#endif

#ifndef ML_MODEL_ACCURACY
#define ML_MODEL_ACCURACY "Train 86.2% | Test 85.1%"
#endif

inline float tree0(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (f_std_30s <= 0.4595f) {
    if (dF_dt_10s <= 0.2575f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        if (v_std_30s <= 0.9478f) {
          return 0.6904f;
        } else {
          return 0.7778f;
        }
      }
    } else {
      if (frequency <= 50.5050f) {
        if (voltage <= 210.1000f) {
          return 0.0000f;
        } else {
          return 0.8033f;
        }
      } else {
        return 0.0000f;
      }
    }
  } else {
    if (dF_dt_10s <= 0.3775f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= 1.6750f) {
          return 0.6676f;
        } else {
          return 0.4494f;
        }
      }
    } else {
      if (dF_dt_10s <= 0.7675f) {
        if (v_slope_30s <= -1.1183f) {
          return 0.4953f;
        } else {
          return 0.1666f;
        }
      } else {
        if (v_slope_30s <= -0.6083f) {
          return 0.0875f;
        } else {
          return 0.0278f;
        }
      }
    }
  }
}

inline float tree1(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (v_slope_30s <= 1.3250f) {
    if (dF_dt_10s <= 0.4955f) {
      if (voltage <= 209.9500f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= -0.6845f) {
          return 0.7031f;
        } else {
          return 0.6114f;
        }
      }
    } else {
      if (dV_dt_10s <= -2.2250f) {
        if (frequency <= 50.5000f) {
          return 0.8818f;
        } else {
          return 0.0000f;
        }
      } else {
        if (dV_dt_10s <= -1.0250f) {
          return 0.0839f;
        } else {
          return 0.0217f;
        }
      }
    }
  } else {
    if (f_std_30s <= 0.4035f) {
      if (frequency <= 50.5050f) {
        if (dF_dt_10s <= -0.1375f) {
          return 0.5938f;
        } else {
          return 0.7989f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (v_slope_30s <= 1.8071f) {
        if (frequency <= 50.5050f) {
          return 0.4633f;
        } else {
          return 0.0000f;
        }
      } else {
        if (dV_dt_10s <= 4.4250f) {
          return 0.2747f;
        } else {
          return 0.1190f;
        }
      }
    }
  }
}

inline float tree2(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (dF_dt_10s <= 0.4175f) {
    if (v_std_30s <= 5.3867f) {
      if (f_std_30s <= 0.2964f) {
        if (voltage <= 209.9500f) {
          return 0.0000f;
        } else {
          return 0.7658f;
        }
      } else {
        if (frequency <= 50.5050f) {
          return 0.6842f;
        } else {
          return 0.0000f;
        }
      }
    } else {
      if (v_slope_30s <= 1.3586f) {
        if (voltage <= 209.9500f) {
          return 0.0000f;
        } else {
          return 0.6481f;
        }
      } else {
        if (f_std_30s <= 0.3474f) {
          return 0.5944f;
        } else {
          return 0.2366f;
        }
      }
    }
  } else {
    if (frequency <= 50.5050f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        if (dV_dt_10s <= 5.1250f) {
          return 0.8505f;
        } else {
          return 0.3333f;
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
