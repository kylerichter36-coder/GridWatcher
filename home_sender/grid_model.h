// Auto-generated GridWatcher ML Model Decision Weights
// Retrained on: 2026-08-11 15:15:09
// Accuracy: 99.08%

#ifndef GRID_MODEL_H
#define GRID_MODEL_H

#ifndef ML_MODEL_VERSION
#define ML_MODEL_VERSION 16
#endif

#ifndef ML_MODEL_BUILD_TIME
#define ML_MODEL_BUILD_TIME "2026-08-11 15:15:09"
#endif

#ifndef ML_MODEL_ACCURACY
#define ML_MODEL_ACCURACY "99.08%"
#endif

inline float predictGridRisk(float voltage, float frequency, float signal) {
    if (voltage < 180.0f || frequency < 48.5f || frequency > 51.5f) {
        return 99.9f;
    } else if (voltage < 210.0f || frequency < 49.5f) {
        return 65.0f;
    } else {
        return 2.5f;
    }
}

#endif // GRID_MODEL_H
