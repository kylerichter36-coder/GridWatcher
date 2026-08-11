// Auto-generated GridWatcher Random Forest ML Decision Trees
// Retrained on: 2026-08-11 18:15:37
// Accuracy: 88.83%

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
#define ML_MODEL_VERSION 18
#endif

#ifndef ML_MODEL_BUILD_TIME
#define ML_MODEL_BUILD_TIME "2026-08-11 18:15:37"
#endif

#ifndef ML_MODEL_ACCURACY
#define ML_MODEL_ACCURACY "88.83%"
#endif

inline float tree0(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (v_std_30s <= 3.5687f) {
    if (dF_dt_10s <= 0.0665f) {
      if (frequency <= 50.5050f) {
        if (v_std_30s <= 1.0403f) {
          return 0.8119f;
        } else {
          return 0.9267f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (frequency <= 50.5050f) {
        if (frequency <= 49.4900f) {
          return 0.0000f;
        } else {
          return 0.9779f;
        }
      } else {
        return 0.0000f;
      }
    }
  } else {
    if (dF_dt_10s <= 0.0935f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= 0.3117f) {
          return 0.8469f;
        } else {
          return 0.5691f;
        }
      }
    } else {
      if (dF_dt_10s <= 0.1435f) {
        if (v_slope_30s <= 0.1683f) {
          return 0.4171f;
        } else {
          return 0.1000f;
        }
      } else {
        if (v_slope_30s <= 0.1183f) {
          return 0.0743f;
        } else {
          return 0.0254f;
        }
      }
    }
  }
}

inline float tree1(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (v_slope_30s <= 0.2450f) {
    if (dF_dt_10s <= 0.1105f) {
      if (voltage <= 209.9500f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= 0.1283f) {
          return 0.7670f;
        } else {
          return 0.6534f;
        }
      }
    } else {
      if (dV_dt_10s <= -0.7450f) {
        if (frequency <= 50.5150f) {
          return 0.9059f;
        } else {
          return 0.0000f;
        }
      } else {
        if (dV_dt_10s <= -0.1950f) {
          return 0.0897f;
        } else {
          return 0.0216f;
        }
      }
    }
  } else {
    if (voltage <= 230.7500f) {
      if (frequency <= 50.5050f) {
        if (dF_dt_10s <= -0.0525f) {
          return 0.5432f;
        } else {
          return 0.9413f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (v_slope_30s <= 0.5950f) {
        if (frequency <= 50.5050f) {
          return 0.5258f;
        } else {
          return 0.0000f;
        }
      } else {
        if (f_std_30s <= 2.2347f) {
          return 0.1840f;
        } else {
          return 0.0909f;
        }
      }
    }
  }
}

inline float tree2(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (dF_dt_10s <= 0.0825f) {
    if (v_std_30s <= 0.4806f) {
      if (signal <= -557.0000f) {
        if (dV_dt_10s <= -0.0050f) {
          return 0.8073f;
        } else {
          return 0.5132f;
        }
      } else {
        if (dV_dt_10s <= -0.0450f) {
          return 0.8799f;
        } else {
          return 0.6963f;
        }
      }
    } else {
      if (v_slope_30s <= 0.2083f) {
        if (dF_dt_10s <= -0.0365f) {
          return 0.6766f;
        } else {
          return 0.8492f;
        }
      } else {
        if (voltage <= 230.7500f) {
          return 0.6296f;
        } else {
          return 0.3751f;
        }
      }
    }
  } else {
    if (dV_dt_10s <= -0.4350f) {
      if (frequency <= 50.5000f) {
        if (voltage <= 210.4000f) {
          return 0.2143f;
        } else {
          return 0.9333f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (frequency <= 50.5050f) {
        if (dV_dt_10s <= 1.1950f) {
          return 0.9226f;
        } else {
          return 0.6400f;
        }
      } else {
        return 0.0000f;
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
