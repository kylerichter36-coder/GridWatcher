#!/usr/bin/env python3
"""
Planned maintenance parser and registry for GridWatcher v0.3.
Matches municipal/utility advisories (e.g. City of Ekurhuleni notices) against
device suburbs and cellular LACs.
"""

import os
import re
import json
import time
from typing import List, Dict, Optional, Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(SCRIPT_DIR, "server_state")
MAINT_FILE = os.path.join(STATE_DIR, "maintenance_windows.json")

# Ekurhuleni & Gauteng suburb -> cell tower LAC mapping
SUBURB_LAC_MAP = {
    "germiston": [1041, 1042],
    "boksburg": [1042, 1043],
    "kempton park": [1044, 1045],
    "edenvale": [1041, 1046],
    "bedfordview": [1041, 1046],
    "benoni": [1047],
    "brakpan": [1048],
    "springs": [1049],
    "alberton": [1050],
    "ekurhuleni": [1041, 1042, 1043, 1044, 1045, 1046, 1047, 1048, 1049, 1050],
}


class MaintenanceRegistry:
    def __init__(self, storage_path: str = MAINT_FILE):
        self.storage_path = storage_path
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        self.windows: List[Dict[str, Any]] = self._load()

    def _load(self) -> List[Dict[str, Any]]:
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        default_windows = [
            {
                "id": "COE-2026-001",
                "source": "City of Ekurhuleni (@CoE_Call_Centre)",
                "suburb": "Boksburg",
                "cell_lacs": [1042, 1043],
                "start_epoch": int(time.time()) + 86400,
                "end_epoch": int(time.time()) + 86400 + 14400,
                "raw_text": (
                    "City of Ekurhuleni Notice: Planned power interruption in Boksburg "
                    "for 11kV substation switchgear maintenance."
                ),
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        ]
        self._save(default_windows)
        return default_windows

    def _save(self, windows: Optional[List[Dict[str, Any]]] = None) -> None:
        if windows is not None:
            self.windows = windows
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(self.windows, f, indent=2)

    def parse_social_notice(
        self,
        raw_text: str,
        start_epoch: Optional[int] = None,
        end_epoch: Optional[int] = None,
        source: str = "City of Ekurhuleni X/Feed",
    ) -> Dict[str, Any]:
        text_lower = raw_text.lower()
        matched_suburbs = []
        matched_lacs = set()

        for suburb, lacs in SUBURB_LAC_MAP.items():
            if suburb in text_lower:
                matched_suburbs.append(suburb.title())
                matched_lacs.update(lacs)

        if not matched_suburbs:
            matched_suburbs = ["Ekurhuleni General"]
            matched_lacs.update(SUBURB_LAC_MAP["ekurhuleni"])

        now = int(time.time())
        if start_epoch is None:
            hr_match = re.search(r"in\s+(\d+)\s*hour", text_lower)
            offset = int(hr_match.group(1)) * 3600 if hr_match else 0
            start_epoch = now + offset
        if end_epoch is None:
            dur_match = re.search(r"for\s+(\d+)\s*hour", text_lower)
            dur = int(dur_match.group(1)) * 3600 if dur_match else (4 * 3600)
            end_epoch = start_epoch + dur

        entry = {
            "id": f"COE-{int(time.time() * 1000) % 1000000:06d}",
            "source": source,
            "suburb": ", ".join(matched_suburbs),
            "cell_lacs": sorted(list(matched_lacs)),
            "start_epoch": int(start_epoch),
            "end_epoch": int(end_epoch),
            "raw_text": raw_text.strip(),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.windows.append(entry)
        self._save()
        return entry

    def check_active_or_upcoming(
        self,
        suburb: Optional[str] = None,
        cell_lac: Optional[int] = None,
        timestamp_epoch: Optional[float] = None,
        lookahead_seconds: int = 1800,
    ) -> Optional[Dict[str, Any]]:
        ts = float(timestamp_epoch if timestamp_epoch is not None else time.time())
        sub_low = suburb.lower().strip() if suburb else ""

        for w in reversed(self.windows):
            start_t = float(w.get("start_epoch", 0)) - lookahead_seconds
            end_t = float(w.get("end_epoch", 0)) + 900  # 15m restoration margin
            if not (start_t <= ts <= end_t):
                continue

            w_sub = str(w.get("suburb", "")).lower()
            w_lacs = w.get("cell_lacs", [])

            if cell_lac is not None and int(cell_lac) in w_lacs:
                return w
            if sub_low and (sub_low in w_sub or w_sub in sub_low):
                return w

        return None

    def list_windows(self) -> List[Dict[str, Any]]:
        return list(self.windows)
