// Generated on: 2026-11-12 06:16:38
// Validation Metrics: Recall@20s: 100.0% | FA/day: 0.00 | PR-AUC: 0.994

#ifndef GRID_MODEL_H
#define GRID_MODEL_H

#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <math.h>
#include "features_gen.h"

enum GridStatus : uint8_t {
    STATUS_NORMAL        = 0,
    STATUS_BROWNOUT_SAG  = 1,
    STATUS_VOLTAGE_SURGE = 2,
    STATUS_FREQ_JITTER   = 3,
    STATUS_BLACKOUT      = 4
};

#ifndef ML_MODEL_VERSION
#define ML_MODEL_VERSION 58
#endif

#ifndef ML_MODEL_BUILD_TIME
#define ML_MODEL_BUILD_TIME "2026-11-12 06:16:38"
#endif

#ifndef ML_MODEL_METRICS
#define ML_MODEL_METRICS "Recall@20s: 100.0% | FA/day: 0.00 | PR-AUC: 0.994"
#endif

#define GW_MAX_DYNAMIC_TREES  24U
#define GW_MAX_DYNAMIC_NODES  1024U

#pragma pack(push, 1)
struct FlatTreeNode {
    int8_t   feature_idx;       // 0..9 feature index, or -1 for leaf
    uint8_t  tree_id;
    int16_t  left_child;
    int16_t  right_child;
    float    threshold_or_prob;
};

struct BinaryModelHeader {
    uint32_t magic;             // 0x47574D33 ('GWM3')
    uint16_t schema_version;    // 3
    uint16_t n_trees;
    uint16_t n_nodes;
    uint16_t reserved;
    uint32_t feature_hash;      // 0xB7DCECA1
    uint32_t model_version;
    uint32_t nodes_crc32;
    uint8_t  hmac_sha256[32];
};
#pragma pack(pop)

static const uint16_t DEFAULT_TREE_ROOTS[9] = { 0, 9, 18, 33, 48, 67, 72, 81, 90 };

static const FlatTreeNode DEFAULT_FLAT_NODES[103] = {
    {  9,  0U,    1,    8, -0.000610f } /* [0] */,
    {  3,  0U,    2,    3, 9.120000f } /* [1] */,
    { -1,  0U,   -1,   -1, 0.000000f } /* [2] */,
    {  3,  0U,    4,    7, 40.329000f } /* [3] */,
    {  3,  0U,    5,    6, 14.372000f } /* [4] */,
    { -1,  0U,   -1,   -1, 0.000000f } /* [5] */,
    { -1,  0U,   -1,   -1, 1.000000f } /* [6] */,
    { -1,  0U,   -1,   -1, 1.000000f } /* [7] */,
    { -1,  0U,   -1,   -1, 0.000000f } /* [8] */,
    {  3,  1U,   10,   11, 8.900000f } /* [9] */,
    { -1,  1U,   -1,   -1, 0.000000f } /* [10] */,
    {  9,  1U,   12,   17, -0.000381f } /* [11] */,
    {  7,  1U,   13,   14, 0.020858f } /* [12] */,
    { -1,  1U,   -1,   -1, 0.000000f } /* [13] */,
    {  6,  1U,   15,   16, 1.463968f } /* [14] */,
    { -1,  1U,   -1,   -1, 0.972222f } /* [15] */,
    { -1,  1U,   -1,   -1, 1.000000f } /* [16] */,
    { -1,  1U,   -1,   -1, 0.000000f } /* [17] */,
    {  3,  2U,   19,   20, 8.809500f } /* [18] */,
    { -1,  2U,   -1,   -1, 0.000000f } /* [19] */,
    {  2,  2U,   21,   28, 49.979549f } /* [20] */,
    {  8,  2U,   22,   25, -0.006792f } /* [21] */,
    {  9,  2U,   23,   24, -0.004315f } /* [22] */,
    { -1,  2U,   -1,   -1, 1.000000f } /* [23] */,
    { -1,  2U,   -1,   -1, 0.976744f } /* [24] */,
    {  6,  2U,   26,   27, 0.461909f } /* [25] */,
    { -1,  2U,   -1,   -1, 0.000000f } /* [26] */,
    { -1,  2U,   -1,   -1, 0.958904f } /* [27] */,
    {  9,  2U,   29,   32, -0.000467f } /* [28] */,
    {  3,  2U,   30,   31, 11.320000f } /* [29] */,
    { -1,  2U,   -1,   -1, 0.000000f } /* [30] */,
    { -1,  2U,   -1,   -1, 0.823529f } /* [31] */,
    { -1,  2U,   -1,   -1, 0.000000f } /* [32] */,
    {  9,  3U,   34,   41, -0.000655f } /* [33] */,
    {  6,  3U,   35,   36, 0.402259f } /* [34] */,
    { -1,  3U,   -1,   -1, 0.000000f } /* [35] */,
    {  3,  3U,   37,   38, 7.731000f } /* [36] */,
    { -1,  3U,   -1,   -1, 0.000000f } /* [37] */,
    {  2,  3U,   39,   40, 49.863201f } /* [38] */,
    { -1,  3U,   -1,   -1, 1.000000f } /* [39] */,
    { -1,  3U,   -1,   -1, 0.969231f } /* [40] */,
    {  3,  3U,   42,   43, 8.410000f } /* [41] */,
    { -1,  3U,   -1,   -1, 0.000000f } /* [42] */,
    {  2,  3U,   44,   47, 49.985298f } /* [43] */,
    {  0,  3U,   45,   46, 227.225006f } /* [44] */,
    { -1,  3U,   -1,   -1, 0.933333f } /* [45] */,
    { -1,  3U,   -1,   -1, 0.000000f } /* [46] */,
    { -1,  3U,   -1,   -1, 0.000000f } /* [47] */,
    {  9,  4U,   49,   60, -0.000634f } /* [48] */,
    {  2,  4U,   50,   55, 49.971109f } /* [49] */,
    {  2,  4U,   51,   54, 49.968800f } /* [50] */,
    {  0,  4U,   52,   53, 227.537003f } /* [51] */,
    { -1,  4U,   -1,   -1, 1.000000f } /* [52] */,
    { -1,  4U,   -1,   -1, 0.973913f } /* [53] */,
    { -1,  4U,   -1,   -1, 0.000000f } /* [54] */,
    {  3,  4U,   56,   57, 8.495500f } /* [55] */,
    { -1,  4U,   -1,   -1, 0.000000f } /* [56] */,
    {  7,  4U,   58,   59, 0.023218f } /* [57] */,
    { -1,  4U,   -1,   -1, 0.000000f } /* [58] */,
    { -1,  4U,   -1,   -1, 0.976744f } /* [59] */,
    {  3,  4U,   61,   62, 8.390000f } /* [60] */,
    { -1,  4U,   -1,   -1, 0.000000f } /* [61] */,
    {  3,  4U,   63,   64, 11.330000f } /* [62] */,
    { -1,  4U,   -1,   -1, 0.000000f } /* [63] */,
    {  3,  4U,   65,   66, 12.361000f } /* [64] */,
    { -1,  4U,   -1,   -1, 0.000000f } /* [65] */,
    { -1,  4U,   -1,   -1, 0.913043f } /* [66] */,
    {  3,  5U,   68,   69, 9.009500f } /* [67] */,
    { -1,  5U,   -1,   -1, 0.000000f } /* [68] */,
    {  3,  5U,   70,   71, 14.831000f } /* [69] */,
    { -1,  5U,   -1,   -1, 0.000000f } /* [70] */,
    { -1,  5U,   -1,   -1, 1.000000f } /* [71] */,
    {  3,  6U,   73,   74, 8.843000f } /* [72] */,
    { -1,  6U,   -1,   -1, 0.000000f } /* [73] */,
    {  3,  6U,   75,   76, 12.200000f } /* [74] */,
    { -1,  6U,   -1,   -1, 0.000000f } /* [75] */,
    {  3,  6U,   77,   80, 36.475001f } /* [76] */,
    {  0,  6U,   78,   79, 225.447998f } /* [77] */,
    { -1,  6U,   -1,   -1, 0.000000f } /* [78] */,
    { -1,  6U,   -1,   -1, 0.736842f } /* [79] */,
    { -1,  6U,   -1,   -1, 1.000000f } /* [80] */,
    {  3,  7U,   82,   83, 8.580000f } /* [81] */,
    { -1,  7U,   -1,   -1, 0.000000f } /* [82] */,
    {  3,  7U,   84,   85, 12.200000f } /* [83] */,
    { -1,  7U,   -1,   -1, 0.000000f } /* [84] */,
    {  2,  7U,   86,   87, 49.903999f } /* [85] */,
    { -1,  7U,   -1,   -1, 1.000000f } /* [86] */,
    {  0,  7U,   88,   89, 226.271799f } /* [87] */,
    { -1,  7U,   -1,   -1, 0.700000f } /* [88] */,
    { -1,  7U,   -1,   -1, 1.000000f } /* [89] */,
    {  3,  8U,   91,   92, 8.870000f } /* [90] */,
    { -1,  8U,   -1,   -1, 0.000000f } /* [91] */,
    {  9,  8U,   93,   98, -0.000897f } /* [92] */,
    {  6,  8U,   94,   97, 1.295236f } /* [93] */,
    {  7,  8U,   95,   96, 0.023864f } /* [94] */,
    { -1,  8U,   -1,   -1, 0.000000f } /* [95] */,
    { -1,  8U,   -1,   -1, 1.000000f } /* [96] */,
    { -1,  8U,   -1,   -1, 1.000000f } /* [97] */,
    {  4,  8U,   99,  102, -0.066500f } /* [98] */,
    {  3,  8U,  100,  101, 10.304000f } /* [99] */,
    { -1,  8U,   -1,   -1, 0.000000f } /* [100] */,
    { -1,  8U,   -1,   -1, 0.777778f } /* [101] */,
    { -1,  8U,   -1,   -1, 0.000000f } /* [102] */
};

struct DynamicEnsembleModel {
    bool         has_custom_model;
    uint32_t     active_version;
    uint16_t     n_trees;
    uint16_t     n_nodes;
    uint16_t     tree_roots[GW_MAX_DYNAMIC_TREES];
    FlatTreeNode nodes[GW_MAX_DYNAMIC_NODES];
};

inline float evaluateLayer2AUnsupervised(const float feat[GW_NUM_FEATURES]) {
    const float v_delta  = feat[FEAT_V_DELTA_BASELINE];
    const float f_hz     = feat[FEAT_F_HZ];
    const float f_jitter = feat[FEAT_F_CYCLE_JITTER];
    const float v_std    = feat[FEAT_V_STD_30S];
    const float f_std    = feat[FEAT_F_STD_30S];
    const float v_slope  = feat[FEAT_V_SLOPE_30S];
    const float f_slope  = feat[FEAT_F_SLOPE_30S];

    float score = 0.0f;
    if (v_delta < -4.0f) {
        float s = fabsf(v_delta + 4.0f) * 2.2f;
        score += (s < 35.0f) ? s : 35.0f;
    }
    if (v_slope < -0.08f) {
        float s = fabsf(v_slope) * 45.0f;
        score += (s < 25.0f) ? s : 25.0f;
    }
    if (fabsf(f_hz - 50.0f) > 0.25f) {
        float s = (fabsf(f_hz - 50.0f) - 0.25f) * 35.0f;
        score += (s < 25.0f) ? s : 25.0f;
    }
    if (f_slope < -0.005f) {
        float s = fabsf(f_slope) * 600.0f;
        score += (s < 20.0f) ? s : 20.0f;
    }
    if (f_jitter > 35.0f) {
        float s = (f_jitter - 35.0f) * 0.25f;
        score += (s < 20.0f) ? s : 20.0f;
    }
    if (v_std > 1.8f) {
        float s = (v_std - 1.8f) * 4.0f;
        score += (s < 15.0f) ? s : 15.0f;
    }
    if (f_std > 0.12f) {
        float s = (f_std - 0.12f) * 35.0f;
        score += (s < 15.0f) ? s : 15.0f;
    }
    return (score > 100.0f) ? 100.0f : score;
}

inline float evaluateFlatNodeArray(
    const float feat[GW_NUM_FEATURES],
    const FlatTreeNode* nodes,
    uint16_t n_nodes,
    const uint16_t* roots,
    uint16_t n_trees
) {
    if (!nodes || !roots || n_trees == 0 || n_nodes == 0) {
        return evaluateLayer2AUnsupervised(feat);
    }
    float prob_sum = 0.0f;
    for (uint16_t t = 0; t < n_trees; ++t) {
        int16_t curr = (int16_t)roots[t];
        uint8_t depth_guard = 0;
        while (curr >= 0 && (uint16_t)curr < n_nodes && depth_guard < 32) {
            const FlatTreeNode& nd = nodes[curr];
            if (nd.feature_idx < 0) {
                prob_sum += nd.threshold_or_prob;
                break;
            }
            if ((uint8_t)nd.feature_idx < GW_NUM_FEATURES && feat[nd.feature_idx] <= nd.threshold_or_prob) {
                curr = nd.left_child;
            } else {
                curr = nd.right_child;
            }
            ++depth_guard;
        }
    }
    return (prob_sum / (float)n_trees) * 100.0f;
}

inline float predictGridRisk(
    const float feat[GW_NUM_FEATURES],
    const DynamicEnsembleModel* dyn_model = nullptr
) {
    if (dyn_model && dyn_model->has_custom_model && dyn_model->n_trees > 0) {
        return evaluateFlatNodeArray(
            feat,
            dyn_model->nodes,
            dyn_model->n_nodes,
            dyn_model->tree_roots,
            dyn_model->n_trees
        );
    }
    return evaluateFlatNodeArray(
        feat,
        DEFAULT_FLAT_NODES,
        (uint16_t)(sizeof(DEFAULT_FLAT_NODES) / sizeof(DEFAULT_FLAT_NODES[0])),
        DEFAULT_TREE_ROOTS,
        (uint16_t)(sizeof(DEFAULT_TREE_ROOTS) / sizeof(DEFAULT_TREE_ROOTS[0]))
    );
}

inline uint32_t gwCrc32Ieee(const uint8_t* data, size_t len) {
    uint32_t crc = 0xFFFFFFFFUL;
    for (size_t i = 0; i < len; ++i) {
        crc ^= (uint32_t)data[i];
        for (uint8_t b = 0; b < 8; ++b) {
            if (crc & 1UL) {
                crc = (crc >> 1) ^ 0xEDB88320UL;
            } else {
                crc >>= 1;
            }
        }
    }
    return ~crc;
}

inline bool loadDynamicBinaryModel(
    const uint8_t* payload,
    size_t len,
    DynamicEnsembleModel* out_model
) {
    if (!payload || !out_model || len < sizeof(BinaryModelHeader)) {
        return false;
    }
    BinaryModelHeader hdr;
    memcpy(&hdr, payload, sizeof(BinaryModelHeader));
    if (hdr.magic != 0x47574D33UL) {
        return false;
    }
    if (hdr.schema_version != GW_SCHEMA_VERSION || hdr.feature_hash != GW_FEATURE_HASH) {
        return false;
    }
    if (hdr.n_trees == 0 || hdr.n_trees > GW_MAX_DYNAMIC_TREES ||
        hdr.n_nodes == 0 || hdr.n_nodes > GW_MAX_DYNAMIC_NODES) {
        return false;
    }
    const size_t roots_bytes = (size_t)hdr.n_trees * sizeof(uint16_t);
    const size_t nodes_bytes = (size_t)hdr.n_nodes * sizeof(FlatTreeNode);
    const size_t body_len = roots_bytes + nodes_bytes;
    if (len < sizeof(BinaryModelHeader) + body_len) {
        return false;
    }
    const uint8_t* body = payload + sizeof(BinaryModelHeader);
    if (gwCrc32Ieee(body, body_len) != hdr.nodes_crc32) {
        return false;
    }
    memcpy(out_model->tree_roots, body, roots_bytes);
    memcpy(out_model->nodes, body + roots_bytes, nodes_bytes);
    out_model->n_trees = hdr.n_trees;
    out_model->n_nodes = hdr.n_nodes;
    out_model->active_version = hdr.model_version;
    out_model->has_custom_model = true;
    return true;
}

#endif // GRID_MODEL_H
