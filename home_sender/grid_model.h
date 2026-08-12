// Auto-generated GridWatcher Random Forest ML Decision Trees
// Retrained on: 2026-08-12 15:06:59
// Accuracy: 82.51%

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
#define ML_MODEL_VERSION 21
#endif

#ifndef ML_MODEL_BUILD_TIME
#define ML_MODEL_BUILD_TIME "2026-08-12 15:06:59"
#endif

#ifndef ML_MODEL_ACCURACY
#define ML_MODEL_ACCURACY "82.51%"
#endif

inline float tree0(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (f_std_30s <= 0.4597f) {
    if (dF_dt_10s <= 0.2775f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        if (v_std_30s <= 0.9478f) {
          return 0.6902f;
        } else {
          return 0.7620f;
        }
      }
    } else {
      if (frequency <= 50.5050f) {
        if (voltage <= 210.0500f) {
          return 0.0000f;
        } else {
          return 0.7853f;
        }
      } else {
        return 0.0000f;
      }
    }
  } else {
    if (dF_dt_10s <= 0.3725f) {
      if (frequency <= 50.5050f) {
        if (v_slope_30s <= 1.2583f) {
          return 0.6807f;
        } else {
          return 0.4089f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (dF_dt_10s <= 0.7375f) {
        if (v_slope_30s <= 0.1708f) {
          return 0.3520f;
        } else {
          return 0.1185f;
        }
      } else {
        if (v_slope_30s <= -0.0750f) {
          return 0.0748f;
        } else {
          return 0.0258f;
        }
      }
    }
  }
}

inline float tree1(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (v_slope_30s <= 1.3208f) {
    if (dF_dt_10s <= 0.4675f) {
      if (voltage <= 209.9500f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= 0.1177f) {
          return 0.6693f;
        } else {
          return 0.5778f;
        }
      }
    } else {
      if (dV_dt_10s <= -2.2250f) {
        if (frequency <= 50.5000f) {
          return 0.8501f;
        } else {
          return 0.0000f;
        }
      } else {
        if (dV_dt_10s <= -1.0250f) {
          return 0.1010f;
        } else {
          return 0.0265f;
        }
      }
    }
  } else {
    if (f_std_30s <= 0.4035f) {
      if (frequency <= 50.5050f) {
        if (dF_dt_10s <= -0.1375f) {
          return 0.6343f;
        } else {
          return 0.7872f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (v_slope_30s <= 1.8071f) {
        if (frequency <= 50.5050f) {
          return 0.4514f;
        } else {
          return 0.0000f;
        }
      } else {
        if (dV_dt_10s <= 4.4250f) {
          return 0.2595f;
        } else {
          return 0.1236f;
        }
      }
    }
  }
}

inline float tree2(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (dF_dt_10s <= 0.4225f) {
    if (v_std_30s <= 5.1355f) {
      if (f_std_30s <= 0.2964f) {
        if (voltage <= 209.9500f) {
          return 0.0000f;
        } else {
          return 0.7598f;
        }
      } else {
        if (frequency <= 50.5050f) {
          return 0.6831f;
        } else {
          return 0.0000f;
        }
      }
    } else {
      if (v_slope_30s <= 1.0083f) {
        if (voltage <= 209.9500f) {
          return 0.0000f;
        } else {
          return 0.6640f;
        }
      } else {
        if (f_std_30s <= 0.3473f) {
          return 0.6250f;
        } else {
          return 0.2737f;
        }
      }
    }
  } else {
    if (frequency <= 50.5050f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        if (dV_dt_10s <= 5.7500f) {
          return 0.8400f;
        } else {
          return 0.4000f;
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
