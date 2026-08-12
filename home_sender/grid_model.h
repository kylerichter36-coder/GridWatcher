// Auto-generated GridWatcher Random Forest ML Decision Trees
// Retrained on: 2026-08-12 17:01:46
// Train Acc: 84.68% | 80/20 Test Holdout Acc: 83.50%

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
#define ML_MODEL_VERSION 25
#endif

#ifndef ML_MODEL_BUILD_TIME
#define ML_MODEL_BUILD_TIME "2026-08-12 17:01:46"
#endif

#ifndef ML_MODEL_ACCURACY
#define ML_MODEL_ACCURACY "Train 84.7% | Test 83.5%"
#endif

inline float tree0(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (f_std_30s <= 2.0815f) {
    if (dF_dt_10s <= 0.3775f) {
      if (frequency <= 49.4950f) {
        return 0.0000f;
      } else {
        if (v_std_30s <= 1.8622f) {
          return 0.5375f;
        } else {
          return 0.7207f;
        }
      }
    } else {
      if (frequency <= 50.5050f) {
        if (frequency <= 49.4900f) {
          return 0.0000f;
        } else {
          return 0.8201f;
        }
      } else {
        return 0.0000f;
      }
    }
  } else {
    if (dF_dt_10s <= 0.4525f) {
      if (frequency <= 50.5050f) {
        if (v_slope_30s <= 0.0594f) {
          return 0.7008f;
        } else {
          return 0.6205f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (dF_dt_10s <= 0.8725f) {
        if (v_slope_30s <= -0.4618f) {
          return 1.0000f;
        } else {
          return 0.2090f;
        }
      } else {
        if (v_slope_30s <= -0.0261f) {
          return 0.0229f;
        } else {
          return 0.0445f;
        }
      }
    }
  }
}

inline float tree1(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (v_slope_30s <= 0.0468f) {
    if (dF_dt_10s <= 0.3625f) {
      if (voltage <= 209.9500f) {
        return 0.0000f;
      } else {
        if (v_slope_30s <= -0.0983f) {
          return 0.6906f;
        } else {
          return 0.6181f;
        }
      }
    } else {
      if (dV_dt_10s <= -2.8750f) {
        if (frequency <= 50.5000f) {
          return 0.8025f;
        } else {
          return 0.0000f;
        }
      } else {
        if (dV_dt_10s <= 0.2583f) {
          return 0.0947f;
        } else {
          return 0.0390f;
        }
      }
    }
  } else {
    if (voltage <= 227.9500f) {
      if (frequency <= 50.5050f) {
        if (dF_dt_10s <= -0.1675f) {
          return 0.6598f;
        } else {
          return 0.8017f;
        }
      } else {
        return 0.0000f;
      }
    } else {
      if (v_slope_30s <= 0.2115f) {
        if (frequency <= 50.5050f) {
          return 0.4791f;
        } else {
          return 0.0000f;
        }
      } else {
        if (dV_dt_10s <= 0.5923f) {
          return 0.4292f;
        } else {
          return 0.1823f;
        }
      }
    }
  }
}

inline float tree2(float voltage, float frequency, float signal, float dV_dt_10s, float dF_dt_10s, float v_std_30s, float f_std_30s, float v_slope_30s) {
  if (dF_dt_10s <= 0.4225f) {
    if (v_std_30s <= 8.6719f) {
      if (f_std_30s <= 0.1790f) {
        if (voltage <= 224.4000f) {
          return 0.0481f;
        } else {
          return 0.8571f;
        }
      } else {
        if (frequency <= 50.5050f) {
          return 0.6983f;
        } else {
          return 0.0000f;
        }
      }
    } else {
      if (v_slope_30s <= 9.2842f) {
        if (voltage <= 210.7000f) {
          return 0.0000f;
        } else {
          return 0.4885f;
        }
      } else {
        if (frequency <= 50.3400f) {
          return 0.8667f;
        } else {
          return 0.0000f;
        }
      }
    }
  } else {
    if (voltage <= 228.0500f) {
      if (dV_dt_10s <= -2.1750f) {
        if (frequency <= 50.4950f) {
          return 0.8600f;
        } else {
          return 0.0000f;
        }
      } else {
        if (v_slope_30s <= -0.4755f) {
          return 0.1613f;
        } else {
          return 0.0402f;
        }
      }
    } else {
      if (v_std_30s <= 67.7307f) {
        if (dF_dt_10s <= 0.5575f) {
          return 0.1109f;
        } else {
          return 0.0193f;
        }
      } else {
        return 1.0000f;
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
