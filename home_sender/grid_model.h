// Auto-generated GridWatcher Random Forest ML Decision Trees
// Retrained on: 2026-08-11 20:53:18
// Accuracy: 85.56%

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
#define ML_MODEL_VERSION 20
#endif

#ifndef ML_MODEL_BUILD_TIME
#define ML_MODEL_BUILD_TIME "2026-08-11 20:53:18"
#endif

#ifndef ML_MODEL_ACCURACY
#define ML_MODEL_ACCURACY "85.56%"
#endif

inline float tree0(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (f_std_30s <= 2.1452f) {
    if (dF_dt_10s <= 0.0815f) {
      if (frequency <= 50.5050f) {
        if (v_slope_30s <= 0.2817f) {
          return 0.8623f;
        } else {
          return 0.5867f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (frequency <= 50.5050f) {
        if (frequency <= 49.4950f) {
          return 0.0000f;
        } else {
          return 0.9849f;
        }
      } else {
        return 0.0000f;
      }
    }
  } else {
    if (dF_dt_10s <= 0.0935f) {
      if (frequency <= 50.5050f) {
        if (v_slope_30s <= 0.2083f) {
          return 0.8541f;
        } else {
          return 0.6113f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (dF_dt_10s <= 0.1435f) {
        if (v_slope_30s <= 0.2100f) {
          return 0.3774f;
        } else {
          return 0.0690f;
        }
      } else {
        if (v_slope_30s <= 0.0017f) {
          return 0.0666f;
        } else {
          return 0.0287f;
        }
      }
    }
  }
}

inline float tree1(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (v_slope_30s <= 0.2383f) {
    if (dF_dt_10s <= 0.1105f) {
      if (voltage <= 209.9500f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= 0.1283f) {
          return 0.7635f;
        } else {
          return 0.6499f;
        }
      }
    } else {
      if (dV_dt_10s <= -0.5950f) {
        if (frequency <= 50.5000f) {
          return 0.8939f;
        } else {
          return 0.0000f;
        }
      } else {
        if (dV_dt_10s <= -0.0950f) {
          return 0.0716f;
        } else {
          return 0.0178f;
        }
      }
    }
  } else {
    if (voltage <= 230.7500f) {
      if (frequency <= 50.5050f) {
        if (dF_dt_10s <= -0.0425f) {
          return 0.5302f;
        } else {
          return 0.9477f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (v_slope_30s <= 0.5950f) {
        if (frequency <= 50.5050f) {
          return 0.5212f;
        } else {
          return 0.0000f;
        }
      } else {
        if (dV_dt_10s <= 1.9700f) {
          return 0.1315f;
        } else {
          return 0.3962f;
        }
      }
    }
  }
}

inline float tree2(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (dF_dt_10s <= 0.0845f) {
    if (v_std_30s <= 0.4806f) {
      if (signal <= -557.0000f) {
        if (dV_dt_10s <= -0.0050f) {
          return 0.8153f;
        } else {
          return 0.5441f;
        }
      } else {
        if (dV_dt_10s <= 0.7800f) {
          return 0.7497f;
        } else {
          return 0.2931f;
        }
      }
    } else {
      if (v_slope_30s <= 0.2083f) {
        if (dF_dt_10s <= -0.0505f) {
          return 0.6730f;
        } else {
          return 0.8349f;
        }
      } else {
        if (voltage <= 227.2500f) {
          return 0.6742f;
        } else {
          return 0.4116f;
        }
      }
    }
  } else {
    if (dV_dt_10s <= -0.4350f) {
      if (frequency <= 50.5000f) {
        if (voltage <= 210.4000f) {
          return 0.2143f;
        } else {
          return 0.9354f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (frequency <= 50.5050f) {
        if (dV_dt_10s <= 1.1950f) {
          return 0.9248f;
        } else {
          return 0.6250f;
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
