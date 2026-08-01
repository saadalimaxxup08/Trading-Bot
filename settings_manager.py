import os
import json
import threading

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
_lock = threading.Lock()

def get_supabase_client():
    try:
        from supabase import create_client, ClientOptions
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            try:
                import streamlit as st
                url = st.secrets.get("SUPABASE_URL")
                key = st.secrets.get("SUPABASE_KEY")
            except:
                pass
        if url and key:
            options = ClientOptions(postgrest_client_timeout=10)
            return create_client(url, key, options=options)
    except:
        pass
    return None

def get_active_data_source():
    # 1. Try to read settings from Supabase so both servers stay synchronized in real-time
    client = get_supabase_client()
    if client is not None:
        try:
            res = client.table("signals").select("status").eq("id", "setting_active_data_source").execute()
            if res.data:
                return res.data[0]["status"]
        except Exception as e:
            print(f"[Settings Supabase Read Error]: {e}")

    # 2. Local fallback if Supabase is offline or not configured yet
    with _lock:
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, "r") as f:
                    data = json.load(f)
                    return data.get("data_source", "Deriv WebSocket")
        except Exception as e:
            print(f"[Settings Manager Local Read Error]: {e}")
        return "Deriv WebSocket"

def set_active_data_source(source):
    # 1. Try to write settings to Supabase
    client = get_supabase_client()
    if client is not None:
        try:
            payload = {
                "id": "setting_active_data_source",
                "time": "1970-01-01T00:00:00+00:00",
                "pair": "SETTINGS",
                "timeframe": "CONFIG",
                "type": "active_data_source",
                "entry_price": 0.0,
                "exit_time": "1970-01-01T00:00:00+00:00",
                "exit_price": 0.0,
                "status": source,
                "strength": "N/A",
                "confirmations": 0,
                "patterns": "N/A"
            }
            client.table("signals").upsert(payload).execute()
            print(f"[Settings] Successfully saved active_data_source='{source}' to Supabase.")
        except Exception as e:
            print(f"[Settings Supabase Write Error]: {e}")

    # 2. Always write to local JSON as secondary fallback
    with _lock:
        try:
            data = {}
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, "r") as f:
                    data = json.load(f)
            data["data_source"] = source
            with open(SETTINGS_FILE, "w") as f:
                json.dump(data, f, indent=4)
            print(f"[Settings] Successfully saved active_data_source='{source}' to local JSON.")
        except Exception as e:
            print(f"[Settings Manager Local Write Error]: {e}")
