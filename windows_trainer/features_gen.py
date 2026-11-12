# Generated from common/features.yaml via windows_trainer/codegen.py

GW_SCHEMA_VERSION = 3
GW_MODEL_MAGIC = 0x47574D33
GW_FEATURE_HASH = 0xB7DCECA1
GW_NUM_FEATURES = 10

FEATURE_NAMES = ['v_rms', 'v_delta_baseline', 'f_hz', 'f_cycle_jitter', 'dV_dt_10s', 'dF_dt_10s', 'v_std_30s', 'f_std_30s', 'v_slope_30s', 'f_slope_30s']

FEATURE_SPECS = [
    {'index': 0, 'name': 'v_rms', 'unit': 'V', 'min_val': 0.0, 'max_val': 300.0, 'default_val': 230.0, 'description': 'True RMS AC line voltage from BL0939'},
    {'index': 1, 'name': 'v_delta_baseline', 'unit': 'V', 'min_val': -60.0, 'max_val': 60.0, 'default_val': 0.0, 'description': "Deviation of RMS voltage from the device's learned local resting baseline"},
    {'index': 2, 'name': 'f_hz', 'unit': 'Hz', 'min_val': 40.0, 'max_val': 65.0, 'default_val': 50.0, 'description': 'Cycle-accurate line frequency from BL0939 ZX zero-crossing capture'},
    {'index': 3, 'name': 'f_cycle_jitter', 'unit': 'mHz', 'min_val': 0.0, 'max_val': 2000.0, 'default_val': 5.0, 'description': '1-second standard deviation of half-cycle ZX frequency in millihertz'},
    {'index': 4, 'name': 'dV_dt_10s', 'unit': 'V/s', 'min_val': -15.0, 'max_val': 15.0, 'default_val': 0.0, 'description': '10-second rolling rate of change of AC voltage'},
    {'index': 5, 'name': 'dF_dt_10s', 'unit': 'Hz/s', 'min_val': -2.0, 'max_val': 2.0, 'default_val': 0.0, 'description': '10-second rolling rate of change of AC line frequency'},
    {'index': 6, 'name': 'v_std_30s', 'unit': 'V', 'min_val': 0.0, 'max_val': 30.0, 'default_val': 0.25, 'description': '30-second rolling population standard deviation of voltage'},
    {'index': 7, 'name': 'f_std_30s', 'unit': 'Hz', 'min_val': 0.0, 'max_val': 5.0, 'default_val': 0.02, 'description': '30-second rolling population standard deviation of frequency'},
    {'index': 8, 'name': 'v_slope_30s', 'unit': 'V/s', 'min_val': -10.0, 'max_val': 10.0, 'default_val': 0.0, 'description': '30-second ordinary least-squares linear regression slope of voltage'},
    {'index': 9, 'name': 'f_slope_30s', 'unit': 'Hz/s', 'min_val': -1.0, 'max_val': 1.0, 'default_val': 0.0, 'description': '30-second ordinary least-squares linear regression slope of frequency'}
]

FEATURE_INDEX = {f["name"]: f["index"] for f in FEATURE_SPECS}
FEATURE_DEFAULTS = {f["name"]: f["default_val"] for f in FEATURE_SPECS}
