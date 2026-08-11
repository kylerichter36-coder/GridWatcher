// Auto-generated GridWatcher Random Forest ML Decision Trees
// Retrained on: 2026-08-11 20:53:37
// Accuracy: 85.74%

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
#define ML_MODEL_BUILD_TIME "2026-08-11 20:53:37"
#endif

#ifndef ML_MODEL_ACCURACY
#define ML_MODEL_ACCURACY "85.74%"
#endif

inline float tree0(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (f_std_30s <= 0.4529f) {
    if (dF_dt_10s <= 0.2775f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        if (v_std_30s <= 0.9478f) {
          return 0.6394f;
        } else {
          return 0.7611f;
        }
      }
    } else {
      if (frequency <= 50.5050f) {
        if (voltage <= 210.1000f) {
          return 0.0000f;
        } else {
          return 0.8009f;
        }
      } else {
        return 0.0000f;
      }
    }
  } else {
    if (dF_dt_10s <= 0.3825f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= 1.6750f) {
          return 0.6605f;
        } else {
          return 0.4366f;
        }
      }
    } else {
      if (dF_dt_10s <= 0.7525f) {
        if (v_slope_30s <= -0.3417f) {
          return 0.4187f;
        } else {
          return 0.1486f;
        }
      } else {
        if (v_slope_30s <= -0.4583f) {
          return 0.0952f;
        } else {
          return 0.0279f;
        }
      }
    }
  }
}

inline float tree1(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (v_slope_30s <= 1.3250f) {
    if (dF_dt_10s <= 0.4525f) {
      if (voltage <= 209.9500f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= -0.6845f) {
          return 0.7025f;
        } else {
          return 0.6025f;
        }
      }
    } else {
      if (dV_dt_10s <= -2.2250f) {
        if (frequency <= 50.4900f) {
          return 0.8609f;
        } else {
          return 0.0000f;
        }
      } else {
        if (dV_dt_10s <= -1.0750f) {
          return 0.1005f;
        } else {
          return 0.0302f;
        }
      }
    }
  } else {
    if (f_std_30s <= 0.4491f) {
      if (frequency <= 50.5050f) {
        if (dF_dt_10s <= -0.0975f) {
          return 0.5857f;
        } else {
          return 0.8005f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (v_slope_30s <= 1.6750f) {
        if (frequency <= 50.5100f) {
          return 0.5085f;
        } else {
          return 0.0000f;
        }
      } else {
        if (dV_dt_10s <= 0.6250f) {
          return 0.3889f;
        } else {
          return 0.1232f;
        }
      }
    }
  }
}

inline float tree2(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (dF_dt_10s <= 0.4225f) {
    if (v_std_30s <= 5.5323f) {
      if (f_std_30s <= 0.3195f) {
        if (voltage <= 209.9500f) {
          return 0.0000f;
        } else {
          return 0.7475f;
        }
      } else {
        if (frequency <= 50.5050f) {
          return 0.6658f;
        } else {
          return 0.0000f;
        }
      }
    } else {
      if (v_slope_30s <= 1.3708f) {
        if (voltage <= 209.9500f) {
          return 0.0000f;
        } else {
          return 0.6438f;
        }
      } else {
        if (f_std_30s <= 0.3006f) {
          return 0.6348f;
        } else {
          return 0.2536f;
        }
      }
    }
  } else {
    if (frequency <= 50.5050f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        if (dV_dt_10s <= 5.7500f) {
          return 0.8418f;
        } else {
          return 0.2273f;
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
