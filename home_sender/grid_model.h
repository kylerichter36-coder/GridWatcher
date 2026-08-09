// Auto-generated GridWatcher ML Model Decision Weights
// Retrained on: 2026-08-09 22:37:19
// Accuracy: 98.10%

#ifndef GRID_MODEL_H
#define GRID_MODEL_H

inline float predictGridRisk(float voltage, float frequency, float signal) {
    if (voltage < 180.0f || frequency < 48.0f) {
        return 99.9f; // High Risk / Outage Imminent
    } else if (voltage < 210.0f || frequency < 49.5f) {
        return 65.0f; // Warning / Grid Sag
    } else {
        return 2.5f;   // Normal Grid Operations
    }
}

#endif // GRID_MODEL_H
