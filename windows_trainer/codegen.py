#!/usr/bin/env python3
"""
Generates firmware/features_gen.h and windows_trainer/features_gen.py
from common/features.yaml so C++ and Python use the exact same feature order.
"""

import os
import zlib

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
YAML_PATH = os.path.join(REPO_DIR, "common", "features.yaml")
CPP_OUT_PATH = os.path.join(REPO_DIR, "firmware", "features_gen.h")
PY_OUT_PATH = os.path.join(SCRIPT_DIR, "features_gen.py")


def parse_features_yaml(path: str) -> dict:
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        data = {"schema_version": 3, "model_magic": 0x47574D33, "features": []}
        current = None
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("schema_version:"):
                data["schema_version"] = int(line.split(":", 1)[1].strip())
            elif line.startswith("model_magic:"):
                val = line.split(":", 1)[1].strip()
                data["model_magic"] = int(val, 16) if val.startswith("0x") else int(val)
            elif line.startswith("- index:"):
                if current is not None:
                    data["features"].append(current)
                current = {"index": int(line.split(":", 1)[1].strip())}
            elif current is not None and ":" in line:
                k, v = line.split(":", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k in ("min_val", "max_val", "default_val"):
                    current[k] = float(v)
                elif k == "index":
                    current[k] = int(v)
                else:
                    current[k] = v
        if current is not None:
            data["features"].append(current)
        return data


def compute_schema_hash(schema: dict) -> int:
    features = sorted(schema["features"], key=lambda f: f["index"])
    canonical = "|".join(f"{f['index']}:{f['name']}:{f['unit']}" for f in features)
    return zlib.crc32(canonical.encode("utf-8")) & 0xFFFFFFFF


def generate():
    schema = parse_features_yaml(YAML_PATH)
    features = sorted(schema["features"], key=lambda f: f["index"])
    for idx, feat in enumerate(features):
        if feat["index"] != idx:
            raise ValueError(f"Feature index mismatch at {idx}: got {feat['index']}")

    schema_hash = compute_schema_hash(schema)
    schema_version = int(schema.get("schema_version", 3))
    model_magic = int(schema.get("model_magic", 0x47574D33))
    num_features = len(features)

    enum_entries = ",\n".join(f"    FEAT_{f['name'].upper()} = {f['index']}" for f in features)
    name_entries = ",\n".join(f'    "{f["name"]}"' for f in features)
    default_entries = ", ".join(f"{f['default_val']:.4f}f" for f in features)

    cpp_content = f"""// Generated from common/features.yaml via windows_trainer/codegen.py
#ifndef FEATURES_GEN_H
#define FEATURES_GEN_H

#include <stdint.h>

#define GW_SCHEMA_VERSION   {schema_version}U
#define GW_MODEL_MAGIC      0x{model_magic:08X}UL
#define GW_FEATURE_HASH     0x{schema_hash:08X}UL
#define GW_NUM_FEATURES     {num_features}U

enum GridFeatureIndex : uint8_t {{
{enum_entries},
    FEAT_COUNT = {num_features}
}};

static const char* const GW_FEATURE_NAMES[GW_NUM_FEATURES] = {{
{name_entries}
}};

static const float GW_FEATURE_DEFAULTS[GW_NUM_FEATURES] = {{
    {default_entries}
}};

struct GridFeatureVector {{
    union {{
        float values[GW_NUM_FEATURES];
        struct {{
            float v_rms;
            float v_delta_baseline;
            float f_hz;
            float f_cycle_jitter;
            float dV_dt_10s;
            float dF_dt_10s;
            float v_std_30s;
            float f_std_30s;
            float v_slope_30s;
            float f_slope_30s;
        }};
    }};
}};

#endif // FEATURES_GEN_H
"""

    os.makedirs(os.path.dirname(CPP_OUT_PATH), exist_ok=True)
    with open(CPP_OUT_PATH, "w", encoding="utf-8") as f:
        f.write(cpp_content)

    py_features_repr = ",\n    ".join(repr(f) for f in features)
    py_names_repr = ", ".join(repr(f["name"]) for f in features)

    py_content = f'''# Generated from common/features.yaml via windows_trainer/codegen.py

GW_SCHEMA_VERSION = {schema_version}
GW_MODEL_MAGIC = 0x{model_magic:08X}
GW_FEATURE_HASH = 0x{schema_hash:08X}
GW_NUM_FEATURES = {num_features}

FEATURE_NAMES = [{py_names_repr}]

FEATURE_SPECS = [
    {py_features_repr}
]

FEATURE_INDEX = {{f["name"]: f["index"] for f in FEATURE_SPECS}}
FEATURE_DEFAULTS = {{f["name"]: f["default_val"] for f in FEATURE_SPECS}}
'''

    with open(PY_OUT_PATH, "w", encoding="utf-8") as f:
        f.write(py_content)

    print(f"[codegen] schema v{schema_version} ({num_features} features, hash 0x{schema_hash:08X})")


if __name__ == "__main__":
    generate()
