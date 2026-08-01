import os
import json
import threading

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
_lock = threading.Lock()

def get_active_data_source():
    with _lock:
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, "r") as f:
                    data = json.load(f)
                    return data.get("data_source", "Deriv WebSocket")
        except Exception as e:
            print(f"[Settings Manager Error]: {e}")
        return "Deriv WebSocket"

def set_active_data_source(source):
    with _lock:
        try:
            data = {}
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, "r") as f:
                    data = json.load(f)
            data["data_source"] = source
            with open(SETTINGS_FILE, "w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"[Settings Manager Error]: {e}")
