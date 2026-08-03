import os
import json
import threading
import time

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
_lock = threading.Lock()

# In-memory settings cache to save database egress
_cache = {}
_CACHE_TTL = 30  # seconds

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
        
        if url:
            url = str(url).strip().strip('"').strip("'")
        if key:
            key = str(key).strip().strip('"').strip("'")
            
        if url and key:
            options = ClientOptions(postgrest_client_timeout=10)
            return create_client(url, key, options=options)
    except:
        pass
    return None

def get_active_data_source():
    now = time.time()
    with _lock:
        if "data_source" in _cache and (now - _cache.get("data_source_time", 0)) < _CACHE_TTL:
            return _cache["data_source"]

    # Cache expired or not found, query Supabase
    client = get_supabase_client()
    source = "Deriv WebSocket"
    if client is not None:
        try:
            res = client.table("signals").select("status").eq("id", "setting_active_data_source").execute()
            if res.data:
                source = res.data[0]["status"]
        except Exception as e:
            print(f"[Settings Supabase Read Error]: {e}")
            # Fallback to local file if database fails
            try:
                if os.path.exists(SETTINGS_FILE):
                    with open(SETTINGS_FILE, "r") as f:
                        data = json.load(f)
                        source = data.get("data_source", "Deriv WebSocket")
            except Exception as read_err:
                print(f"[Local Settings Fallback Read Error]: {read_err}")

    with _lock:
        _cache["data_source"] = source
        _cache["data_source_time"] = now
    return source

def set_active_data_source(source):
    # Invalidate cache
    with _lock:
        if "data_source" in _cache:
            del _cache["data_source"]

    # Write to Supabase
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

    # Write to local JSON
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

def get_active_host():
    now = time.time()
    with _lock:
        if "active_host" in _cache and (now - _cache.get("active_host_time", 0)) < _CACHE_TTL:
            return _cache["active_host"]

    # Cache expired or not found, query Supabase
    client = get_supabase_client()
    host = "Render"
    if client is not None:
        try:
            res = client.table("signals").select("status").eq("id", "setting_active_host").execute()
            if res.data:
                host = res.data[0]["status"]
        except Exception as e:
            print(f"[Settings Supabase Read Host Error]: {e}")

    with _lock:
        _cache["active_host"] = host
        _cache["active_host_time"] = now
    return host

def set_active_host(host):
    # Invalidate cache
    with _lock:
        if "active_host" in _cache:
            del _cache["active_host"]

    import datetime
    client = get_supabase_client()
    if client is not None:
        try:
            payload = {
                "id": "setting_active_host",
                "time": datetime.datetime.utcnow().isoformat() + "+00:00",
                "pair": "SETTINGS",
                "timeframe": "CONFIG",
                "type": "active_host",
                "entry_price": 0.0,
                "exit_time": "1970-01-01T00:00:00+00:00",
                "exit_price": 0.0,
                "status": host,
                "strength": "N/A",
                "confirmations": 0,
                "patterns": "N/A"
            }
            client.table("signals").upsert(payload).execute()
            print(f"[Settings] Successfully saved active_host='{host}' to Supabase.")
        except Exception as e:
            print(f"[Settings Supabase Write Host Error]: {e}")
