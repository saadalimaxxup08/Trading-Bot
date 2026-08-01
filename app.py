import streamlit as st
import asyncio
import websockets
import settings_manager
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import datetime
import pytz
import requests
import time
import os
import json
from dotenv import load_dotenv
import os
# Load env using absolute path of current folder
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, ".env")
load_dotenv(dotenv_path=env_path)

def get_secret(key, default=None):
    val = os.environ.get(key)
    if val:
        return val.strip().strip('"').strip("'")
    try:
        if hasattr(st, "secrets") and key in st.secrets:
            val_st = st.secrets[key]
            if val_st:
                return str(val_st).strip().strip('"').strip("'")
    except Exception:
        pass
    return default

from supabase import create_client, Client, ClientOptions

def trigger_confetti():
    import streamlit.components.v1 as components
    components.html("""
    <script src="https://cdn.jsdelivr.net/npm/canvas-confetti@1.6.0/dist/confetti.browser.min.js"></script>
    <script>
        setTimeout(function() {
            confetti({
                particleCount: 180,
                spread: 100,
                origin: { y: 0.6 },
                colors: ['#ffd700', '#00ff88', '#ffffff']
            });
        }, 100);
    </script>
    """, height=0)

# Setup page config for a premium wide layout
st.set_page_config(
    page_title="Binary Pro Scanner V4 - Sniper Edition",
    layout="wide",
    page_icon="📈",
    initial_sidebar_state="expanded"
)

DERIV_SYMBOL_MAP = {
    # Forex Majors
    "EURUSD=X": "frxEURUSD",
    "GBPUSD=X": "frxGBPUSD",
    "USDJPY=X": "frxUSDJPY",
    "AUDUSD=X": "frxAUDUSD",
    "USDCAD=X": "frxUSDCAD",
    "USDCHF=X": "frxUSDCHF",
    "EURGBP=X": "frxEURGBP",
    "EURJPY=X": "frxEURJPY",
    "GBPJPY=X": "frxGBPJPY",
    
    # Forex Minors
    "AUDCAD=X": "frxAUDCAD",
    "AUDCHF=X": "frxAUDCHF",
    "AUDJPY=X": "frxAUDJPY",
    "AUDNZD=X": "frxAUDNZD",
    "EURAUD=X": "frxEURAUD",
    "EURCAD=X": "frxEURCAD",
    "EURCHF=X": "frxEURCHF",
    "GBPAUD=X": "frxGBPAUD",
    "GBPCAD=X": "frxGBPCAD",
    "NZDUSD=X": "frxNZDUSD",
    
    # Cryptocurrencies
    "BTC-USD": "cryBTCUSD",
    "ETH-USD": "cryETHUSD",
    "LTC-USD": "cryLTCUSD",
    
    # Commodities & Metals
    "GC=F": "frxXAUUSD",
    "SI=F": "frxXAGUSD",
    "CL=F": "frxUKOIL",
    
    # Synthetic Indices (Deriv Only)
    "VOL_10": "R_10",
    "VOL_25": "R_25",
    "VOL_50": "R_50",
    "VOL_75": "R_75",
    "VOL_100": "R_100",
    "VOL_10_1S": "1HZ10V",
    "VOL_25_1S": "1HZ25V",
    "VOL_50_1S": "1HZ50V",
    "VOL_75_1S": "1HZ75V",
    "VOL_100_1S": "1HZ100V",
    "CRASH_300": "C300",
    "BOOM_300": "B300",
    "CRASH_500": "C500",
    "BOOM_500": "B500",
    "CRASH_1000": "C1000",
    "BOOM_1000": "B1000"
}

async def _fetch_deriv_candles_async(symbol, granularity_seconds, count):
    url = "wss://ws.derivws.com/websockets/v3?app_id=1089"
    async with websockets.connect(url, ping_interval=None) as ws:
        request = {
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": count,
            "end": "latest",
            "style": "candles",
            "granularity": granularity_seconds
        }
        await ws.send(json.dumps(request))
        response = await ws.recv()
        data = json.loads(response)
        if "error" in data:
            raise Exception(f"Deriv API error: {data['error'].get('message')}")
        return data.get("candles", [])

def download_deriv_candles(pair, timeframe, count=250):
    try:
        deriv_symbol = DERIV_SYMBOL_MAP.get(pair)
        if not deriv_symbol:
            print(f"[Deriv Data Loader]: Pair {pair} not mapped to Deriv symbols.")
            return pd.DataFrame()
            
        granularity = 300 if timeframe == "5m" else (900 if timeframe == "15m" else 60)
        
        # Run async function synchronously
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            candles = loop.run_until_complete(_fetch_deriv_candles_async(deriv_symbol, granularity, count))
        finally:
            loop.close()
            
        if not candles:
            return pd.DataFrame()
            
        records = []
        for c in candles:
            records.append({
                "Time": pd.to_datetime(c["epoch"], unit="s", utc=True),
                "Open": float(c["open"]),
                "High": float(c["high"]),
                "Low": float(c["low"]),
                "Close": float(c["close"]),
                "Volume": 0.0
            })
            
        df = pd.DataFrame(records)
        df.set_index("Time", inplace=True)
        return df
    except Exception as e:
        print(f"[Deriv Data Loader Error] for {pair}: {e}")
        return pd.DataFrame()

def download_market_data(pair, timeframe, period="2d", count=250):
    source = settings_manager.get_active_data_source()
    if source == "Deriv WebSocket":
        df = download_deriv_candles(pair, timeframe, count=count)
        if not df.empty:
            return df
        print(f"[Data Loader]: Deriv fetch failed/empty for {pair}, falling back to yfinance.")
        
    try:
        df = yf.download(pair, period=period, interval=timeframe, progress=False, threads=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        print(f"[yfinance Fallback Error] for {pair}: {e}")
        return pd.DataFrame()

def download_market_batch(pairs, timeframe, period="5d", count=250):
    source = settings_manager.get_active_data_source()
    if source == "Deriv WebSocket":
        dfs = {}
        for pair in pairs:
            df = download_deriv_candles(pair, timeframe, count=count)
            if not df.empty:
                dfs[pair] = df
        if dfs:
            df_batch = pd.concat(dfs.values(), axis=1, keys=dfs.keys())
            return df_batch
        print("[Data Loader]: Deriv batch fetch failed/empty, falling back to yfinance.")
        
    try:
        df_batch = yf.download(pairs, period=period, interval=timeframe, group_by="ticker", progress=False, threads=True)
        return df_batch
    except Exception as e:
        print(f"[yfinance Batch Fallback Error]: {e}")
        return pd.DataFrame()

# Global settings dictionary to share state with background thread
GLOBAL_SETTINGS = {
    "session_filter_enabled": True
}
session_filter_enabled = GLOBAL_SETTINGS["session_filter_enabled"]

# Custom premium dark styling (VIP Trading Dashboard)
st.markdown("""
<style>
    /* Premium Glassmorphism Theme */
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700;800&display=swap');
    
    .stApp {
        background: linear-gradient(135deg, #050510 0%, #0a0a20 50%, #15102a 100%) !important;
        font-family: 'Outfit', sans-serif !important;
        color: #e2e8f0 !important;
    }
    
    /* Custom Scrollbars */
    ::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }
    ::-webkit-scrollbar-track {
        background: rgba(10, 10, 30, 0.5);
    }
    ::-webkit-scrollbar-thumb {
        background: rgba(255, 215, 0, 0.3);
        border-radius: 4px;
    }
    ::-webkit-scrollbar-thumb:hover {
        background: rgba(255, 215, 0, 0.6);
    }

    /* Glassmorphic Card Container */
    .vip-card {
        background: rgba(20, 20, 45, 0.45) !important;
        backdrop-filter: blur(12px) !important;
        -webkit-backdrop-filter: blur(12px) !important;
        border: 1px solid rgba(255, 215, 0, 0.15) !important;
        border-radius: 16px !important;
        padding: 20px !important;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37) !important;
        margin-bottom: 20px !important;
        transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1) !important;
    }
    .vip-card:hover {
        border-color: rgba(255, 215, 0, 0.4) !important;
        box-shadow: 0 12px 40px 0 rgba(255, 215, 0, 0.1) !important;
        transform: translateY(-2px) !important;
    }

    /* KPI Grid */
    .kpi-container {
        display: flex;
        gap: 15px;
        margin-bottom: 25px;
    }
    .kpi-card {
        flex: 1;
        background: linear-gradient(135deg, rgba(26, 26, 58, 0.6) 0%, rgba(15, 15, 35, 0.6) 100%);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        position: relative;
        overflow: hidden;
        backdrop-filter: blur(10px);
    }
    .kpi-card::before {
        content: '';
        position: absolute;
        top: -50%;
        left: -50%;
        width: 200%;
        height: 200%;
        background: radial-gradient(circle, rgba(255,215,0,0.05) 0%, transparent 70%);
        pointer-events: none;
    }
    .kpi-title {
        font-size: 0.85rem;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        margin-bottom: 8px;
        font-weight: 600;
    }
    .kpi-value {
        font-size: 2.2rem;
        font-weight: 800;
        background: linear-gradient(90deg, #ffffff 0%, #fef08a 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }
    .kpi-accent-gold {
        border: 1px solid rgba(255, 215, 0, 0.3) !important;
        box-shadow: 0 0 15px rgba(255, 215, 0, 0.05);
    }
    .kpi-accent-green {
        border: 1px solid rgba(0, 255, 136, 0.3) !important;
        box-shadow: 0 0 15px rgba(0, 255, 136, 0.05);
    }

    /* Stylish Buttons */
    .stButton>button {
        background: linear-gradient(90deg, #ffd700 0%, #b8860b 100%) !important;
        color: #050510 !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 12px 28px !important;
        font-weight: 700 !important;
        font-size: 0.95rem !important;
        letter-spacing: 0.05em !important;
        text-transform: uppercase !important;
        box-shadow: 0 4px 15px rgba(255, 215, 0, 0.2) !important;
        transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275) !important;
    }
    .stButton>button:hover {
        transform: translateY(-2px) scale(1.02) !important;
        box-shadow: 0 6px 20px rgba(255, 215, 0, 0.4) !important;
    }
    .stButton>button:active {
        transform: translateY(1px) !important;
    }

    /* Badges */
    .vip-badge {
        padding: 5px 12px;
        border-radius: 20px;
        font-weight: 700;
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        display: inline-flex;
        align-items: center;
        gap: 6px;
        border: 1px solid rgba(255, 255, 255, 0.1);
        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    }
    .vip-badge-win {
        background: rgba(0, 255, 136, 0.12) !important;
        color: #00ff88 !important;
        border-color: rgba(0, 255, 136, 0.3) !important;
    }
    .vip-badge-loss {
        background: rgba(255, 7, 58, 0.12) !important;
        color: #ff073a !important;
        border-color: rgba(255, 7, 58, 0.3) !important;
    }
    .vip-badge-pending {
        background: rgba(255, 215, 0, 0.1) !important;
        color: #ffd700 !important;
        border-color: rgba(255, 215, 0, 0.3) !important;
    }
    
    /* Header Session Glow */
    .glow-green {
        box-shadow: 0 0 12px #00ff88;
        animation: pulse-glow 2s infinite alternate;
    }
    .glow-gold {
        box-shadow: 0 0 12px #ffd700;
        animation: pulse-glow-gold 2s infinite alternate;
    }
    
    @keyframes pulse-glow {
        0% { box-shadow: 0 0 4px rgba(0, 255, 136, 0.4); }
        100% { box-shadow: 0 0 16px rgba(0, 255, 136, 0.8); }
    }
    @keyframes pulse-glow-gold {
        0% { box-shadow: 0 0 4px rgba(255, 215, 0, 0.4); }
        100% { box-shadow: 0 0 16px rgba(255, 215, 0, 0.8); }
    }

    /* Signal Card Pulse Glow (Animations) */
    .signal-pulse-card {
        animation: signal-entry-glow 3s cubic-bezier(0.25, 0.8, 0.25, 1) forwards;
    }
    @keyframes signal-entry-glow {
        0% {
            border-color: #ffd700;
            box-shadow: 0 0 30px rgba(255, 215, 0, 0.6);
            transform: scale(1.02);
        }
        100% {
            border-color: rgba(255, 215, 0, 0.15);
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
            transform: scale(1);
        }
    }

    /* Shimmer Skeleton Loading Shimmer Effect */
    .shimmer {
        background: linear-gradient(90deg, #15152e 25%, #25254e 50%, #15152e 75%);
        background-size: 200% 100%;
        animation: loading-shimmer 1.5s infinite;
        border-radius: 8px;
        height: 18px;
        margin: 10px 0;
    }
    @keyframes loading-shimmer {
        0% { background-position: 200% 0; }
        100% { background-position: -200% 0; }
    }

    /* Live scrolling ticker styling */
    .ticker-container {
        overflow: hidden;
        height: 400px;
        position: relative;
        border: 1px solid rgba(255,255,255,0.05);
        border-radius: 12px;
        background: rgba(10, 10, 25, 0.3);
        padding: 10px;
    }
    .ticker-track {
        display: flex;
        flex-direction: column;
        gap: 10px;
        animation: ticker-vertical-scroll 25s linear infinite;
    }
    .ticker-track:hover {
        animation-play-state: paused;
    }
    @keyframes ticker-vertical-scroll {
        0% { transform: translateY(0); }
        100% { transform: translateY(-50%); }
    }

    /* VIP Table hover styles */
    .vip-table {
        width: 100%;
        border-collapse: collapse;
        margin: 15px 0;
        background: rgba(20, 20, 45, 0.2);
        border-radius: 12px;
        overflow: hidden;
        border: 1px solid rgba(255,255,255,0.05);
    }
    .vip-table th {
        background: rgba(255, 215, 0, 0.05) !important;
        color: #ffd700 !important;
        font-weight: 700 !important;
        text-transform: uppercase !important;
        font-size: 0.8rem !important;
        padding: 12px 16px !important;
        border-bottom: 1px solid rgba(255,215,0,0.15) !important;
        text-align: left;
    }
    .vip-table td {
        padding: 12px 16px !important;
        border-bottom: 1px solid rgba(255,255,255,0.03) !important;
        color: #cbd5e1 !important;
        font-size: 0.85rem !important;
    }
    .vip-table tr:hover {
        background: rgba(255, 215, 0, 0.03) !important;
    }
    .tr-win {
        background: rgba(0, 255, 136, 0.02) !important;
    }
    .tr-win:hover {
        background: rgba(0, 255, 136, 0.05) !important;
    }
    .tr-loss {
        background: rgba(255, 7, 58, 0.02) !important;
    }
    .tr-loss:hover {
        background: rgba(255, 7, 58, 0.05) !important;
    }
</style>
""", unsafe_allow_html=True)

# Try loading forex-python for sidebar utility
try:
    from forex_python.converter import CurrencyRates
    rates = CurrencyRates()
except Exception:
    rates = None

# Initialize persistent session states
if "selected_pair" not in st.session_state:
    st.session_state.selected_pair = "EURUSD=X"
if "scanning" not in st.session_state:
    st.session_state.scanning = True
if "signal_history" not in st.session_state:
    st.session_state.signal_history = []
if "daily_losses" not in st.session_state:
    st.session_state.daily_losses = 0
if "last_processed_candle" not in st.session_state:
    st.session_state.last_processed_candle = None
if "news_cached_data" not in st.session_state:
    st.session_state.news_cached_data = []
if "news_last_fetched" not in st.session_state:
    st.session_state.news_last_fetched = 0

# ----------------- SUPABASE AUTH & DB CLIENT -----------------
SUPABASE_URL = get_secret("SUPABASE_URL", "https://your-project-id.supabase.co")
SUPABASE_KEY = get_secret("SUPABASE_KEY", "your-supabase-anon-key-here")
APP_URL = get_secret("APP_URL", "http://localhost:8501/")

# Global dictionary to store PKCE verifiers across session reloads
if not hasattr(st, "_pending_verifiers"):
    st._pending_verifiers = {}

def get_supabase_client():
    if not SUPABASE_URL or "your-project-id" in SUPABASE_URL or "your-supabase-anon" in SUPABASE_KEY:
        return None
    try:
        # Use PKCE flow for secure magic links
        options = ClientOptions(auto_refresh_token=False, persist_session=False, flow_type="pkce")
        return create_client(SUPABASE_URL, SUPABASE_KEY, options=options)
    except Exception:
        return None

supabase_client = get_supabase_client()

# Global System Health monitoring class (replaces worker state imports)
class SystemHealth:
    LAST_SCAN_TIME = "N/A"
    LAST_SELF_TEST_TIME = None

# Local set to prevent duplicate signal processing in memory
if not hasattr(st, "_processed_signals"):
    st._processed_signals = set()

def local_send_telegram_alert(text):
    tg_token = get_secret("TELEGRAM_BOT_TOKEN")
    tg_chat_id = get_secret("TELEGRAM_CHAT_ID")
    if not tg_token or not tg_chat_id:
        print("[Telegram Alert Warning] Missing Token or Chat ID in environment.")
        return False
    url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
    payload = {
        "chat_id": tg_chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        print(f"[Telegram Alert Error] Failed to send message: {e}")
        return False

def local_get_session_type(time_obj):
    if time_obj.tzinfo is None:
        time_obj = pytz.utc.localize(time_obj)
    time_ry = time_obj.astimezone(pytz.timezone("Asia/Riyadh"))
    # London + NY session overlap: 10:00 AM AST to 10:00 PM AST
    if 10 <= time_ry.hour < 22:
        return "IN-SESSION"
    return "OFF-SESSION"

def local_process_market_signals_prefetched(pair, timeframe, df_pair):
    if df_pair.empty or len(df_pair) < 2:
        return False
        
    try:
        closed_candle = df_pair.iloc[-2]
        closed_time = df_pair.index[-2]
        
        # Unique signal ID constraint
        sig_id = f"{pair}-{timeframe.upper()}-{closed_time.strftime('%Y%m%d%H%M')}"
        
        if sig_id in st._processed_signals:
            return False
            
        if supabase_client is not None:
            try:
                dup_check = supabase_client.table("signals").select("id").eq("id", sig_id).execute()
                if dup_check.data:
                    st._processed_signals.add(sig_id)
                    return False
            except Exception as e:
                print(f"[DB Duplicate Warning]: {e}")
                
        # Calculate indicators
        df_indicators = calculate_indicators(df_pair.copy())
        df_res = check_signals(df_indicators, pair)
        
        if df_res.empty or len(df_res) < 2:
            return False
            
        live_row = df_res.iloc[-2]
        
        sig_type = None
        call_score = int(live_row.get('Call_Score', 0))
        put_score = int(live_row.get('Put_Score', 0))
        if call_score == 5:
            sig_type = "CALL"
        elif put_score == 5:
            sig_type = "PUT"
            
        if sig_type is None:
            return False
            
        # Verify Session overlap limit
        session_type = local_get_session_type(closed_time)
        if session_type != "IN-SESSION":
            print(f"[SCAN BLOCKED] {pair} {timeframe} - OFF-SESSION at {closed_time}")
            return False
            
        now_ast = datetime.datetime.now(pytz.timezone("Asia/Riyadh"))
        now_utc = now_ast.astimezone(pytz.utc)
        time_str_ast = f"{now_ast.strftime('%I:%M %p AST')} ({now_utc.strftime('%I:%M %p UTC')})"
        exit_time = closed_time + datetime.timedelta(minutes=15)
        
        # ── Extract ALL raw indicator values for detailed logging ──
        macd_val = float(live_row.get('MACD', 0))
        signal_val = float(live_row.get('MACD_Signal', 0))
        bb_lower_val = float(live_row.get('BB_Lower', 0))
        bb_upper_val = float(live_row.get('BB_Upper', 0))
        bb_middle_val = float(live_row.get('BB_Middle', 0))
        vol_val = float(live_row.get('Volume', 0))
        rsi_val = float(live_row.get('RSI_14', 0))
        ema50_val = float(live_row.get('EMA_50', 0))
        ema200_val = float(live_row.get('EMA_200', 0))
        ema_slope = float(live_row.get('EMA_200_Slope', 0))
        atr_spike_flag = bool(live_row.get('ATR_Spike', False))
        close_price = float(closed_candle['Close'])
        open_price = float(closed_candle['Open'])
        high_price = float(closed_candle['High'])
        low_price = float(closed_candle['Low'])
        
        # ── Compute individual rule booleans (mirror check_signals logic) ──
        macd_prev = float(df_res['MACD'].iloc[-3]) if len(df_res) >= 3 else 0
        signal_prev = float(df_res['MACD_Signal'].iloc[-3]) if len(df_res) >= 3 else 0
        
        macd_cross_call = (macd_prev <= signal_prev) and (macd_val > signal_val)
        macd_cross_put = (macd_prev >= signal_prev) and (macd_val < signal_val)
        macd_cross_ok = macd_cross_call if sig_type == "CALL" else macd_cross_put
        
        bb_touch_call = (low_price <= bb_lower_val) and (close_price > open_price)
        bb_touch_put = (high_price >= bb_upper_val) and (close_price < open_price)
        bb_touch_ok = bb_touch_call if sig_type == "CALL" else bb_touch_put
        
        # Volume spike: current > previous
        vol_prev = float(df_pair['Volume'].iloc[-3]) if len(df_pair) >= 3 else 0
        volume_spike_ok = vol_val > vol_prev
        
        ema200_slope_up = ema_slope > 0
        
        # Additional V4.2 filters that were checked
        rsi_room_ok = (rsi_val < 45) if sig_type == "CALL" else (rsi_val > 55)
        ema_trend_ok = (close_price > ema50_val or ema50_val > ema200_val) if sig_type == "CALL" else (close_price < ema50_val or ema50_val < ema200_val)
        
        # Pips multiplier for swing pivot check
        is_jpy = "JPY" in str(pair)
        pips_mult = 0.01 if is_jpy else 0.0001
        ten_pips = 10 * pips_mult
        swing_low_val = float(live_row.get('Swing_Low_20', 0))
        swing_high_val = float(live_row.get('Swing_High_20', 0))
        swing_pivot_ok = (abs(bb_lower_val - swing_low_val) <= ten_pips) if sig_type == "CALL" else (abs(bb_upper_val - swing_high_val) <= ten_pips)
        
        # ── Build structured reason_details JSON ──
        reason_details = {
            "direction": sig_type,
            "call_score": call_score,
            "put_score": put_score,
            # Individual rule booleans
            "macd_cross": macd_cross_ok,
            "bb_touch": bb_touch_ok,
            "volume_spike": volume_spike_ok,
            "ema200_slope_up": ema200_slope_up,
            "rsi_room_ok": rsi_room_ok,
            "ema_trend_ok": ema_trend_ok,
            "atr_spike": atr_spike_flag,
            "swing_pivot_ok": swing_pivot_ok,
            # Raw indicator values
            "macd_value": round(macd_val, 6),
            "macd_signal_value": round(signal_val, 6),
            "bb_lower": round(bb_lower_val, 5),
            "bb_upper": round(bb_upper_val, 5),
            "bb_middle": round(bb_middle_val, 5),
            "rsi_14": round(rsi_val, 2),
            "ema_50": round(ema50_val, 5),
            "ema_200": round(ema200_val, 5),
            "ema_200_slope": round(ema_slope, 7),
            "current_vol": round(vol_val, 0),
            "prev_vol": round(vol_prev, 0),
            # OHLC snapshot of the closed candle
            "open": round(open_price, 5),
            "high": round(high_price, 5),
            "low": round(low_price, 5),
            "close": round(close_price, 5),
            "session_type": session_type
        }
        
        # Legacy diagnostics string (backward compatible)
        diagnostics_str = f"Type: {sig_type} | MACD: {macd_val:.5f} (Signal: {signal_val:.5f}) | BB Lower: {bb_lower_val:.5f} (Upper: {bb_upper_val:.5f}) | Volume: {vol_val} | RSI: {rsi_val:.2f}"
        
        new_sig = {
            "id": sig_id,
            "time": closed_time.isoformat() if hasattr(closed_time, "isoformat") else str(closed_time),
            "pair": pair,
            "timeframe": timeframe.upper(),  # Strictly "15M"
            "type": sig_type,
            "entry_price": close_price,
            "exit_time": exit_time.isoformat() if hasattr(exit_time, "isoformat") else str(exit_time),
            "exit_price": None,
            "status": "PENDING",
            "strength": "NORMAL",
            "confirmations": "5/5",
            "patterns": "None",
            "diagnostics": diagnostics_str,
            "reason_details": reason_details
        }
        
        if supabase_client is not None:
            try:
                supabase_client.table("signals").insert(new_sig).execute()
                print(f"[DB Saved] Signal {sig_id} | reason_details stored")
            except Exception as dbi_e:
                print(f"[DB Save Error] Failed to save {sig_id}: {dbi_e}")
                
        # ── Telegram alert with detailed reason breakdown ──
        dir_emoji = "🟢 CALL" if sig_type == "CALL" else "🔴 PUT"
        rules_summary = (
            f"• MACD Cross: {'✅' if macd_cross_ok else '❌'}\n"
            f"• BB Touch: {'✅' if bb_touch_ok else '❌'}\n"
            f"• Volume Spike: {'✅' if volume_spike_ok else '❌'}\n"
            f"• EMA200 Slope: {'✅ Up' if ema200_slope_up else '❌ Down'}\n"
            f"• RSI Room: {'✅' if rsi_room_ok else '❌'} ({rsi_val:.1f})\n"
            f"• EMA Trend: {'✅' if ema_trend_ok else '❌'}"
        )
        alert_msg = f"✅ <b>V4.2 SNIPER SIGNAL DETECTED</b>\n\n" \
                    f"<b>Pair:</b> {pair.replace('=X', '')}\n" \
                    f"<b>Direction:</b> {dir_emoji}\n" \
                    f"<b>Entry Price:</b> {close_price:.5f}\n" \
                    f"<b>Session:</b> 🟢 IN-SESSION\n" \
                    f"<b>Entry Time:</b> {time_str_ast}\n" \
                    f"<b>Expiry:</b> 15 Minutes\n\n" \
                    f"<b>📋 Rule Breakdown (5/5):</b>\n{rules_summary}\n\n" \
                    f"<b>Risk:</b> Low"
        local_send_telegram_alert(alert_msg)
        
        st._processed_signals.add(sig_id)
        return True
    except Exception as e:
        print(f"[local_process_market_signals_prefetched Error]: {e}")
        return False

def local_resolve_pending_signals():
    if supabase_client is None:
        return
        
    try:
        res = supabase_client.table("signals").select("*").eq("status", "PENDING").execute()
        pending = res.data if res.data else []
        if not pending:
            return
            
        print(f"[PENDING RESOLUTION] Resolving {len(pending)} pending signals...")
        now_utc = datetime.datetime.now(pytz.utc)
        
        for sig in pending:
            exit_time_utc = pd.to_datetime(sig["exit_time"])
            if exit_time_utc.tzinfo is None:
                exit_time_utc = pytz.utc.localize(exit_time_utc)
                
            if now_utc >= exit_time_utc:
                pair = sig["pair"]
                # Enforce lowercase timeframe in yfinance query
                df = download_market_data(pair, "15m", period="1d")
                if df.empty:
                    continue
                    
                exit_candle = df[df.index == exit_time_utc]
                if exit_candle.empty:
                    closest_idx = df.index.get_indexer([exit_time_utc], method='nearest')[0]
                    exit_price = float(df['Close'].iloc[closest_idx])
                    actual_exit_time = df.index[closest_idx]
                else:
                    exit_price = float(exit_candle['Close'].iloc[0])
                    actual_exit_time = exit_time_utc
                    
                entry_price = float(sig["entry_price"])
                sig_type = sig["type"]
                
                status = "TIE"
                if sig_type == "CALL":
                    if exit_price > entry_price:
                        status = "WIN"
                    elif exit_price < entry_price:
                        status = "LOSS"
                else:
                    if exit_price < entry_price:
                        status = "WIN"
                    elif exit_price > entry_price:
                        status = "LOSS"
                
                # ── Calculate PnL in pips ──
                is_jpy = "JPY" in str(pair)
                pip_divisor = 0.01 if is_jpy else 0.0001
                raw_diff = exit_price - entry_price
                if sig_type == "PUT":
                    raw_diff = -raw_diff  # For PUT, profit = entry - exit
                pnl_pips = round(raw_diff / pip_divisor, 1)
                
                resolved_at_utc = datetime.datetime.now(pytz.utc).isoformat()
                
                update_payload = {
                    "exit_price": exit_price,
                    "status": status,
                    "pnl_pips": pnl_pips,
                    "resolved_at": resolved_at_utc
                }
                supabase_client.table("signals").update(update_payload).eq("id", sig["id"]).execute()
                
                # ── Build detailed outcome message ──
                status_emoji = "🟢 WIN" if status == "WIN" else ("🔴 LOSS" if status == "LOSS" else "🟡 TIE")
                pips_str = f"+{pnl_pips}" if pnl_pips > 0 else str(pnl_pips)
                
                # Why did it win/lose?
                if status == "WIN":
                    reason_str = f"Price moved {abs(pnl_pips):.1f} pips in favor ({'up' if sig_type == 'CALL' else 'down'})"
                elif status == "LOSS":
                    reason_str = f"Price moved {abs(pnl_pips):.1f} pips against ({'down' if sig_type == 'CALL' else 'up'})"
                else:
                    reason_str = "Price unchanged at expiry"
                
                outcome_msg = f"📉 <b>TRADE RESOLVED ({status})</b>\n\n" \
                              f"<b>Pair:</b> {pair.replace('=X', '')}\n" \
                              f"<b>Type:</b> {sig_type}\n" \
                              f"<b>Entry Price:</b> {entry_price:.5f}\n" \
                              f"<b>Exit Price:</b> {exit_price:.5f}\n" \
                              f"<b>P/L:</b> {pips_str} pips\n" \
                              f"<b>Status:</b> {status_emoji}\n" \
                              f"<b>Why:</b> {reason_str}\n" \
                              f"<b>Resolved Time:</b> {actual_exit_time.astimezone(pytz.timezone('Asia/Riyadh')).strftime('%I:%M %p AST')}"
                local_send_telegram_alert(outcome_msg)
                print(f"[RESOLVED] {sig['id']} -> {status} | {pips_str} pips")
    except Exception as e:
        print(f"[local_resolve_pending_signals Error]: {e}")

def local_send_hourly_summary():
    if supabase_client is None:
        return
        
    try:
        now_utc = datetime.datetime.now(pytz.utc)
        one_hour_ago = now_utc - datetime.timedelta(hours=1)
        res = supabase_client.table("signals").select("*").gte("time", one_hour_ago.isoformat()).execute()
        signals = res.data if res.data else []
        
        sig_15m = [s for s in signals if s["timeframe"].upper() == "15M"]
        if not sig_15m:
            return
            
        wins = sum(1 for s in sig_15m if s["status"] == "WIN")
        losses = sum(1 for s in sig_15m if s["status"] == "LOSS")
        ties = sum(1 for s in sig_15m if s["status"] == "TIE")
        pending = sum(1 for s in sig_15m if s["status"] == "PENDING")
        total = wins + losses + ties
        
        win_rate = (wins / total * 100) if total > 0 else 0.0
        
        tz_ry = pytz.timezone("Asia/Riyadh")
        now_ry = now_utc.astimezone(tz_ry)
        start_period = (now_ry - datetime.timedelta(hours=1)).strftime("%I:00 %p")
        end_period = now_ry.strftime("%I:00 %p")
        
        sum_msg = f"🕒 <b>HOURLY PERFORMANCE SUMMARY</b>\n" \
                  f"⏱️ <b>Period:</b> <code>{start_period} - {end_period} AST</code>\n\n" \
                  f"<b>Stats (15M Timeframe):</b>\n" \
                  f"• Wins: {wins} | Losses: {losses} | Ties: {ties}\n" \
                  f"• Pending: {pending}\n" \
                  f"• Win Rate: <b>{win_rate:.1f}%</b>\n"
        
        # ── Total Pips P/L ──
        resolved_sigs = [s for s in sig_15m if s.get("pnl_pips") is not None]
        if resolved_sigs:
            total_pips = sum(float(s["pnl_pips"]) for s in resolved_sigs)
            pips_emoji = "📈" if total_pips >= 0 else "📉"
            sum_msg += f"• {pips_emoji} Total Pips: <b>{total_pips:+.1f}</b>\n"
        
        # ── Per-Pair Breakdown ──
        pairs_seen = {}
        for s in sig_15m:
            p = s["pair"].replace("=X", "")
            if p not in pairs_seen:
                pairs_seen[p] = {"w": 0, "l": 0, "pips": 0.0}
            if s["status"] == "WIN":
                pairs_seen[p]["w"] += 1
            elif s["status"] == "LOSS":
                pairs_seen[p]["l"] += 1
            if s.get("pnl_pips") is not None:
                pairs_seen[p]["pips"] += float(s["pnl_pips"])
        
        if pairs_seen:
            sum_msg += f"\n<b>Per-Pair Breakdown:</b>\n"
            for p_name, p_stats in pairs_seen.items():
                sum_msg += f"• {p_name}: {p_stats['w']}W/{p_stats['l']}L ({p_stats['pips']:+.1f} pips)\n"
        
        sum_msg += f"\n<b>Trades Detail:</b>\n"
                  
        for s in sig_15m[:10]:
            sig_time_ry = pd.to_datetime(s["time"]).astimezone(tz_ry)
            status_char = "🟢" if s["status"] == "WIN" else ("🔴" if s["status"] == "LOSS" else ("🟡" if s["status"] == "TIE" else "⏳"))
            pips_info = f" ({float(s['pnl_pips']):+.1f}p)" if s.get("pnl_pips") is not None else ""
            entry_p = float(s["entry_price"]) if s.get("entry_price") else 0.0
            sum_msg += f"• <code>{sig_time_ry.strftime('%I:%M %p')}</code> | <b>{s['pair'].replace('=X','')}</b> | {s['type']} | {entry_p:.5f} | {status_char}{pips_info}\n"
            
        local_send_telegram_alert(sum_msg)
    except Exception as e:
        print(f"[local_send_hourly_summary Error]: {e}")

def local_send_daily_summary():
    if supabase_client is None:
        return
        
    try:
        now_utc = datetime.datetime.now(pytz.utc)
        one_day_ago = now_utc - datetime.timedelta(days=1)
        res = supabase_client.table("signals").select("*").gte("time", one_day_ago.isoformat()).execute()
        signals = res.data if res.data else []
        
        sig_15m = [s for s in signals if s["timeframe"].upper() == "15M"]
        wins = sum(1 for s in sig_15m if s["status"] == "WIN")
        losses = sum(1 for s in sig_15m if s["status"] == "LOSS")
        ties = sum(1 for s in sig_15m if s["status"] == "TIE")
        total = wins + losses + ties
        
        win_rate = (wins / total * 100) if total > 0 else 0.0
        
        # ── Pips totals ──
        resolved_sigs = [s for s in sig_15m if s.get("pnl_pips") is not None]
        total_pips = sum(float(s["pnl_pips"]) for s in resolved_sigs) if resolved_sigs else 0.0
        avg_win_pips = 0.0
        avg_loss_pips = 0.0
        win_sigs = [s for s in resolved_sigs if s["status"] == "WIN"]
        loss_sigs = [s for s in resolved_sigs if s["status"] == "LOSS"]
        if win_sigs:
            avg_win_pips = sum(float(s["pnl_pips"]) for s in win_sigs) / len(win_sigs)
        if loss_sigs:
            avg_loss_pips = sum(float(s["pnl_pips"]) for s in loss_sigs) / len(loss_sigs)
        
        daily_msg = f"🏆 <b>DAILY SNAPSHOT PERFORMANCE (9:00 PM AST)</b>\n\n" \
                    f"<b>24h Summary (15M Timeframe):</b>\n" \
                    f"• Total Trades: {total}\n" \
                    f"• Wins: {wins} | Losses: {losses} | Ties: {ties}\n" \
                    f"• Win Rate: <b>{win_rate:.1f}%</b>\n" \
                    f"• Total Pips: <b>{total_pips:+.1f}</b>\n" \
                    f"• Avg Win: {avg_win_pips:+.1f} pips | Avg Loss: {avg_loss_pips:.1f} pips\n"
        
        # ── Per-Pair Performance ──
        pairs_stats = {}
        for s in sig_15m:
            p = s["pair"].replace("=X", "")
            if p not in pairs_stats:
                pairs_stats[p] = {"w": 0, "l": 0, "t": 0, "pips": 0.0}
            if s["status"] == "WIN":
                pairs_stats[p]["w"] += 1
            elif s["status"] == "LOSS":
                pairs_stats[p]["l"] += 1
            elif s["status"] == "TIE":
                pairs_stats[p]["t"] += 1
            if s.get("pnl_pips") is not None:
                pairs_stats[p]["pips"] += float(s["pnl_pips"])
        
        if pairs_stats:
            daily_msg += f"\n<b>📊 Per-Pair Stats:</b>\n"
            # Sort by pips descending (best first)
            for p_name, ps in sorted(pairs_stats.items(), key=lambda x: x[1]["pips"], reverse=True):
                p_total = ps["w"] + ps["l"] + ps["t"]
                p_wr = (ps["w"] / p_total * 100) if p_total > 0 else 0
                daily_msg += f"• {p_name}: {ps['w']}W/{ps['l']}L/{ps['t']}T | WR: {p_wr:.0f}% | {ps['pips']:+.1f}p\n"
        
        # ── Rule-wise Accuracy Analysis (from reason_details) ──
        sigs_with_reasons = [s for s in sig_15m if s.get("reason_details") and s["status"] in ("WIN", "LOSS")]
        if sigs_with_reasons:
            rules = ["macd_cross", "bb_touch", "volume_spike", "ema200_slope_up", "rsi_room_ok", "ema_trend_ok"]
            daily_msg += f"\n<b>🔬 Rule Analysis ({len(sigs_with_reasons)} trades):</b>\n"
            for rule in rules:
                true_count = sum(1 for s in sigs_with_reasons if s["reason_details"].get(rule, False))
                true_wins = sum(1 for s in sigs_with_reasons if s["reason_details"].get(rule, False) and s["status"] == "WIN")
                rule_wr = (true_wins / true_count * 100) if true_count > 0 else 0
                rule_label = rule.replace("_", " ").title()
                daily_msg += f"• {rule_label}: {true_count}/{len(sigs_with_reasons)} active | WR: {rule_wr:.0f}%\n"
        
        daily_msg += f"\n<i>V4.2 Sniper Engine — Detailed analytics powered by reason_details logging.</i>"
        local_send_telegram_alert(daily_msg)
    except Exception as e:
        print(f"[local_send_daily_summary Error]: {e}")

# Start background scanner thread in the cloud automatically
@st.cache_resource
def start_background_scanner():
    import threading
    import time
    import worker
    import pytz
    
    sent_pre_alerts = {}
    
    def scanner_thread_func():
        print("[START] 24/7 Cloud Background Scanner Active")
        import datetime
        last_daily_sent_date = None
        last_hourly_sent_hour = None
        last_session_alert_hour = None
        while True:
            try:
                # Reload environment variables in case they were updated via UI/save
                from dotenv import load_dotenv
                current_dir = os.path.dirname(os.path.abspath(__file__))
                env_path = os.path.join(current_dir, ".env")
                load_dotenv(dotenv_path=env_path, override=True)
                
                # Print live heartbeat log to console
                print(f"[HEARTBEAT] Cloud Background Scanner active and scanning 8 pairs - {datetime.datetime.now().strftime('%H:%M:%S')}")
                
                # Run the scanning process using high-speed parallel batch downloading (Strict V4.2 15m)
                for timeframe in ["15m"]:
                    lookback = "5d"
                    try:
                        # Fetch all tickers in parallel in a single HTTP request (extremely fast)
                        df_batch = download_market_batch(RADAR_PAIRS, timeframe, period=lookback)
                        if not df_batch.empty:
                            for pair in RADAR_PAIRS:
                                if len(RADAR_PAIRS) > 1 and pair in df_batch.columns.get_level_values(0):
                                    df_pair = df_batch[pair].dropna(subset=['Close'])
                                else:
                                    df_pair = df_batch.dropna(subset=['Close'])
                                    
                                # Check if we are in the Pre-Alert window (20 seconds before the candle closes)
                                now_utc = datetime.datetime.now(pytz.utc)
                                is_pre_alert_window = (now_utc.minute % 15 == 14) and (40 <= now_utc.second <= 59)
                                    
                                if is_pre_alert_window:
                                    try:
                                        df_pre = calculate_indicators(df_pair.copy())
                                        df_pre = check_signals(df_pre, pair)
                                        if len(df_pre) >= 1:
                                            live_row = df_pre.iloc[-1]
                                            live_time = df_pre.index[-1]
                                            
                                            min_pre_score = 4
                                            pre_sig_type = None
                                            if live_row.get('Call_Score', 0) >= min_pre_score:
                                                pre_sig_type = "CALL"
                                            elif live_row.get('Put_Score', 0) >= min_pre_score:
                                                pre_sig_type = "PUT"
                                                
                                            if pre_sig_type:
                                                pre_session_type = local_get_session_type(live_time)
                                                if pre_session_type == "IN-SESSION":
                                                    pre_session_label = "🟢 IN-SESSION"
                                                    pre_key = (pair, timeframe, live_time)
                                                    if pre_key not in sent_pre_alerts:
                                                        sent_pre_alerts[pre_key] = (pre_sig_type, pre_session_label)
                                                        if len(sent_pre_alerts) > 100:
                                                            sent_pre_alerts.pop(next(iter(sent_pre_alerts)))
                                                        
                                                        # Format and send Pre-Alert to Telegram
                                                        now_ast = datetime.datetime.now(pytz.timezone("Asia/Riyadh"))
                                                        now_utc = now_ast.astimezone(pytz.utc)
                                                        pre_time_str = f"{now_ast.strftime('%I:%M:%S %p AST')} ({now_utc.strftime('%I:%M:%S %p UTC')})"
                                                        pre_dir = "🟢 CALL" if pre_sig_type == "CALL" else "🔴 PUT"
                                                        pre_msg = f"🚨 <b>PRE-ALERT LOADING...</b>\n\n" \
                                                                  f"<b>Pair:</b> {pair.replace('=X', '')}\n" \
                                                                  f"<b>Direction:</b> {pre_dir}\n" \
                                                                  f"<b>Session:</b> {pre_session_label}\n" \
                                                                  f"<b>Time:</b> {pre_time_str}\n" \
                                                                  f"<b>Status:</b> Waiting for final 20s confirmation...\n" \
                                                                  f"<b>Note:</b> Ye Final Signal nahi hai. Sirf Alert hai."
                                                        local_send_telegram_alert(pre_msg)
                                                        print(f"[PRE-ALERT] Sent pre-alert for {pair} {timeframe} {pre_sig_type}")
                                    except Exception as pre_e:
                                        print(f"Pre-alert calculation error: {pre_e}")
                                        
                                # Determine expected closed candle time to evaluate cancel outcome
                                delta_t = datetime.timedelta(minutes=15)
                                last_candle_time = df_pair.index[-1]
                                last_candle_end = last_candle_time + delta_t
                                if now_utc >= last_candle_end:
                                    closed_time = df_pair.index[-1]
                                else:
                                    closed_time = df_pair.index[-2]
                                    
                                pre_key = (pair, timeframe, closed_time)
                                
                                # Process final signal
                                signal_triggered = local_process_market_signals_prefetched(pair, timeframe, df_pair)
                                
                                # Handle Pre-Alert outcome
                                if pre_key in sent_pre_alerts:
                                    pre_dir, pre_session_label = sent_pre_alerts[pre_key]
                                    if signal_triggered:
                                        sent_pre_alerts.pop(pre_key, None)
                                    else:
                                        # Signal failed to confirm! Send cancel alert
                                        now_ast = datetime.datetime.now(pytz.timezone("Asia/Riyadh"))
                                        now_utc = now_ast.astimezone(pytz.utc)
                                        cancel_time_str = f"{now_ast.strftime('%I:%M:%S %p AST')} ({now_utc.strftime('%I:%M:%S %p UTC')})"
                                        cancel_msg = f"❌ <b>SIGNAL CANCELLED</b>\n\n" \
                                                     f"<b>Pair:</b> {pair.replace('=X', '')}\n" \
                                                     f"<b>Direction:</b> {pre_dir}\n" \
                                                     f"<b>Session:</b> {pre_session_label}\n" \
                                                     f"<b>Time:</b> {cancel_time_str}\n" \
                                                     f"<b>Reason:</b> Signal Not Perfect. Last confirmation failed.\n" \
                                                     f"<b>Status:</b> Plan Changed. Waiting for next setup."
                                        local_send_telegram_alert(cancel_msg)
                                        sent_pre_alerts.pop(pre_key, None)
                    except Exception as e:
                        print(f"Batch download error for {timeframe}: {e}")
                    time.sleep(1.0)
                
                try:
                    local_resolve_pending_signals()
                except Exception as res_e:
                    print(f"Error resolving pending signals: {res_e}")
                
                # Update last scan time in system health monitor (Jeddah Time AST)
                SystemHealth.LAST_SCAN_TIME = datetime.datetime.now(pytz.timezone("Asia/Riyadh")).strftime('%I:%M:%S %p AST')
                
                # Check current time in Saudi Arabia (Jeddah/Riyadh)
                tz_ry = pytz.timezone("Asia/Riyadh")
                now_ry = datetime.datetime.now(tz_ry)
                
                # 1. Hourly Summary Trigger (at the start of every hour, e.g., 5:00 PM, 6:00 PM)
                hour_key = now_ry.strftime("%Y-%m-%d-%H")
                if now_ry.minute == 0 and last_hourly_sent_hour != hour_key:
                    local_send_hourly_summary()
                    last_hourly_sent_hour = hour_key
                
                # 2. Daily Summary Trigger (at 9:00 PM Saudi Arabia Time)
                date_key = now_ry.strftime("%Y-%m-%d")
                if now_ry.hour == 21 and now_ry.minute == 0 and last_daily_sent_date != date_key:
                    local_send_daily_summary()
                    last_daily_sent_date = date_key
                
                # 3. Session Start/End Alerts (at transition hours)
                if now_ry.minute == 0 and last_session_alert_hour != hour_key:
                    current_hour = now_ry.hour
                    session_msg = ""
                    if current_hour == 1:
                        session_msg = "🇦🇺 <b>Sydney Session (Australia)</b> has started! Get ready!"
                    elif current_hour == 3:
                        session_msg = "🇯🇵 <b>Tokyo Session (Asia)</b> has started! Get ready!"
                    elif current_hour == 10:
                        session_msg = "🇬🇧 <b>London Session (Europe)</b> has started! High volatility expected. Get ready!\n🇦🇺 Sydney Session is now closed."
                    elif current_hour == 12:
                        session_msg = "🇯🇵 Tokyo Session is now closed."
                    elif current_hour == 15:
                        session_msg = "🇺🇸 <b>New York Session (US)</b> has started! Overlap with London active. High volatility expected. Get ready!"
                    elif current_hour == 19:
                        session_msg = "🇬🇧 London Session is now closed."
                    elif current_hour == 0:
                        session_msg = "🇺🇸 New York Session is now closed."
                    
                    if session_msg:
                        local_send_telegram_alert(session_msg)
                    last_session_alert_hour = hour_key
                
                # 4. Auto Self-Test Every 6 Hours (V4.2 Diagnostics check)
                now_utc = datetime.datetime.now(pytz.utc)
                if SystemHealth.LAST_SELF_TEST_TIME is None:
                    # Run immediately on first thread loop to verify setup
                    SystemHealth.LAST_SELF_TEST_TIME = now_utc - datetime.timedelta(hours=6)
                    
                if (now_utc - SystemHealth.LAST_SELF_TEST_TIME).total_seconds() >= 21600:
                    import requests
                    db_ok = False
                    try:
                        supabase_client.table("signals").select("*").limit(1).execute()
                        db_ok = True
                    except Exception:
                        pass
                        
                    tg_ok = False
                    try:
                        tg_token = get_secret("TELEGRAM_BOT_TOKEN")
                        url_tg = f"https://api.telegram.org/bot{tg_token}/getMe"
                        res_tg = requests.get(url_tg, timeout=5)
                        if res_tg.status_code == 200:
                            tg_ok = True
                    except Exception:
                        pass
                        
                    data_provider_ok = False
                    try:
                        df_test = download_market_data("EURUSD=X", "15m", period="1d")
                        if not df_test.empty:
                            data_provider_ok = True
                    except Exception:
                        pass
                        
                    thread_alive = any(t.name == "scanner_thread_func" for t in threading.enumerate())
                    
                    # Calculate signals and win rate in last 6 hours
                    six_hours_ago = now_utc - datetime.timedelta(hours=6)
                    total_6h = 0
                    wr_6h = 0.0
                    if db_ok:
                        try:
                            res_6h = supabase_client.table("signals").select("*").gte("time", six_hours_ago.isoformat()).execute()
                            sigs_6h = res_6h.data if res_6h.data else []
                            sigs_15m_6h = [s for s in sigs_6h if s["timeframe"].upper() == "15M"]
                            total_6h = len(sigs_15m_6h)
                            resolved_6h = [s for s in sigs_15m_6h if s["status"] in ["WIN", "LOSS"]]
                            wins_6h = sum(1 for s in resolved_6h if s["status"] == "WIN")
                            wr_6h = (wins_6h / len(resolved_6h) * 100) if resolved_6h else 0.0
                        except Exception as e_6h:
                            print(f"Error calculating 6h stats for heartbeat: {e_6h}")
                            
                    active_provider = settings_manager.get_active_data_source()
                    if db_ok and tg_ok and data_provider_ok and thread_alive:
                        status_msg = "🟢 <b>SYSTEM OK: Scanner Alive</b>\n\n" \
                                     "• Supabase DB: Connected\n" \
                                     f"• Data Provider ({active_provider}): Online\n" \
                                     "• Telegram Bot: Valid\n" \
                                     f"• Last 6H: {total_6h} Signals\n" \
                                     f"• WR: <b>{wr_6h:.1f}%</b>"
                        local_send_telegram_alert(status_msg)
                    else:
                        alert_msg = "🚨 <b>SYSTEM ALERT: Diagnostics Failure!</b>\n\n" \
                                    f"• Scanner Thread: {'🟢 Alive' if thread_alive else '🔴 DEAD'}\n" \
                                    f"• Supabase DB: {'🟢 Connected' if db_ok else '🔴 FAILED'}\n" \
                                    f"• Data Provider ({active_provider}): {'🟢 Online' if data_provider_ok else '🔴 OFFLINE'}\n" \
                                    f"• Telegram Bot: {'🟢 Valid' if tg_ok else '🔴 INVALID'}"
                        local_send_telegram_alert(alert_msg)
                        
                    SystemHealth.LAST_SELF_TEST_TIME = now_utc
                
                time.sleep(10)
            except Exception as e:
                print(f"Background scanner loop error: {e}")
                time.sleep(15)
                
    thread = threading.Thread(target=scanner_thread_func, name="scanner_thread_func", daemon=True)
    thread.start()
    return thread

if supabase_client is not None:
    start_background_scanner()

def fetch_signals_from_db(pair, timeframe):
    if supabase_client is None:
        return []
    try:
        res = supabase_client.table("signals").select("*").eq("pair", pair).eq("timeframe", timeframe.upper()).order("time", desc=True).limit(50).execute()
        signals = []
        for r in (res.data if res.data else []):
            try:
                sig_time = pd.to_datetime(r["time"]).to_pydatetime()
                if sig_time.tzinfo is None:
                    sig_time = pytz.utc.localize(sig_time)
                else:
                    sig_time = sig_time.astimezone(pytz.utc)
                
                sig_exit_time = pd.to_datetime(r["exit_time"]).to_pydatetime()
                if sig_exit_time.tzinfo is None:
                    sig_exit_time = pytz.utc.localize(sig_exit_time)
                else:
                    sig_exit_time = sig_exit_time.astimezone(pytz.utc)
                    
                signals.append({
                    "id": r["id"],
                    "time": sig_time,
                    "pair": r["pair"],
                    "timeframe": r["timeframe"],
                    "type": r["type"],
                    "entry_price": float(r["entry_price"]),
                    "exit_time": sig_exit_time,
                    "exit_price": float(r["exit_price"]) if r["exit_price"] is not None else None,
                    "status": r["status"],
                    "strength": r["strength"],
                    "confirmations": r["confirmations"],
                    "patterns": r["patterns"]
                })
            except Exception:
                pass
        return signals
    except Exception:
        return []

def fetch_all_signals_from_db(limit=200):
    if supabase_client is None:
        return []
    try:
        res = supabase_client.table("signals").select("*").order("time", desc=True).limit(limit).execute()
        signals = []
        for r in (res.data if res.data else []):
            try:
                sig_time = pd.to_datetime(r["time"]).to_pydatetime()
                if sig_time.tzinfo is None:
                    sig_time = pytz.utc.localize(sig_time)
                else:
                    sig_time = sig_time.astimezone(pytz.utc)
                
                sig_exit_time = pd.to_datetime(r["exit_time"]).to_pydatetime()
                if sig_exit_time.tzinfo is None:
                    sig_exit_time = pytz.utc.localize(sig_exit_time)
                else:
                    sig_exit_time = sig_exit_time.astimezone(pytz.utc)
                    
                signals.append({
                    "id": r["id"],
                    "time": sig_time,
                    "pair": r["pair"],
                    "timeframe": r["timeframe"],
                    "type": r["type"],
                    "entry_price": float(r["entry_price"]),
                    "exit_time": sig_exit_time,
                    "exit_price": float(r["exit_price"]) if r["exit_price"] is not None else None,
                    "status": r["status"],
                    "strength": r["strength"],
                    "confirmations": r["confirmations"],
                    "patterns": r["patterns"]
                })
            except Exception:
                pass
        return signals
    except Exception:
        return []

def save_signal_to_db(sig):
    if supabase_client is None:
        return
    try:
        sig_data = {
            "id": sig["id"],
            "time": sig["time"].isoformat() if hasattr(sig["time"], "isoformat") else str(sig["time"]),
            "pair": sig["pair"],
            "timeframe": sig["timeframe"],
            "type": sig["type"],
            "entry_price": float(sig["entry_price"]),
            "exit_time": sig["exit_time"].isoformat() if hasattr(sig["exit_time"], "isoformat") else str(sig["exit_time"]),
            "exit_price": float(sig["exit_price"]) if sig["exit_price"] is not None else None,
            "status": sig["status"],
            "strength": sig["strength"],
            "confirmations": sig["confirmations"],
            "patterns": sig["patterns"]
        }
        # Include reason_details if available
        if sig.get("reason_details"):
            sig_data["reason_details"] = sig["reason_details"]
        supabase_client.table("signals").insert(sig_data).execute()
    except Exception as e:
        print(f"Failed to save signal to database: {e}")

def update_signal_in_db(sig):
    if supabase_client is None:
        return
    try:
        payload = {
            "exit_price": float(sig["exit_price"]) if sig["exit_price"] is not None else None,
            "status": sig["status"]
        }
        # Include pnl_pips and resolved_at if available
        if sig.get("pnl_pips") is not None:
            payload["pnl_pips"] = sig["pnl_pips"]
        if sig.get("resolved_at"):
            payload["resolved_at"] = sig["resolved_at"]
        supabase_client.table("signals").update(payload).eq("id", sig["id"]).execute()
    except Exception as e:
        print(f"Failed to update signal in database: {e}")

# Secure login screen check
if supabase_client is not None:
    # 1. Restore session from refresh token (rt) in query params if available
    if "supabase_user" not in st.session_state and "rt" in st.query_params:
        try:
            res = supabase_client.auth.refresh_session(st.query_params["rt"])
            if res.user:
                st.session_state.supabase_user = res.user
                st.query_params["rt"] = res.session.refresh_token
        except Exception:
            # Token invalid or expired, clear it
            st.query_params.pop("rt", None)

    # 2. Check if redirect query parameters exist (passed on Magic Link click)
    if "code" in st.query_params and "email" in st.query_params:
        code = st.query_params["code"]
        email = st.query_params["email"]
        # Extract code_verifier directly from query params or fallback to global dict
        code_verifier = st.query_params.get("verifier") or st._pending_verifiers.get(email)
        if code_verifier:
            try:
                res = supabase_client.auth.exchange_code_for_session({
                    "auth_code": code,
                    "code_verifier": code_verifier
                })
                if res.user:
                    st.session_state.supabase_user = res.user
                    st.query_params.clear()
                    st.query_params["rt"] = res.session.refresh_token
                    st._pending_verifiers.pop(email, None)
                    st.success("Authenticated Successfully!")
                    st.rerun()
            except Exception as e:
                st.error(f"Failed to authenticate magic link: {e}")
        else:
            st.error("Authentication session expired. Please request a new magic link.")

    if "supabase_user" not in st.session_state:
        # Inject Premium Glowing Style Sheet for Login Portal
        st.markdown("""
        <style>
            div[data-testid="stAppViewContainer"] {
                background: radial-gradient(circle at 50% 30%, #1a103c 0%, #030712 70%) !important;
            }
            .login-container {
                max-width: 480px;
                margin: 60px auto;
                background: rgba(17, 24, 39, 0.7);
                border: 1px solid rgba(99, 102, 241, 0.25);
                border-radius: 20px;
                padding: 40px;
                text-align: center;
                box-shadow: 0 0 45px rgba(99, 102, 241, 0.2);
                backdrop-filter: blur(16px);
            }
            .glow-title {
                font-family: 'Inter', sans-serif;
                font-size: 2.2rem;
                font-weight: 800;
                background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                text-shadow: 0 0 30px rgba(99,102,241,0.25);
            }
            .glow-btn button {
                background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%) !important;
                border: none !important;
                box-shadow: 0 4px 15px rgba(99,102,241,0.4) !important;
                transition: all 0.3s ease !important;
                color: white !important;
                font-weight: bold !important;
            }
            .glow-btn button:hover {
                box-shadow: 0 6px 20px rgba(99,102,241,0.6) !important;
                transform: translateY(-2px) !important;
            }
        </style>
        """, unsafe_allow_html=True)

        if "otp_sent" not in st.session_state:
            st.session_state.otp_sent = False
        if "login_email" not in st.session_state:
            st.session_state.login_email = ""

        col_auth_l, col_auth_mid, col_auth_r = st.columns([1, 2, 1])
        with col_auth_mid:
            st.markdown("<div class='login-container'>", unsafe_allow_html=True)
            st.markdown("<div class='glow-title'>⚡ BINARY PRO</div>", unsafe_allow_html=True)
            st.markdown("<div style='color:#a1a1aa; font-size:0.95rem; margin-bottom:30px;'>VIP Trading Access Portal</div>", unsafe_allow_html=True)

            auth_tab1, auth_tab2 = st.tabs(["📩 Magic Link", "🔑 Password"])
            
            with auth_tab1:
                if not st.session_state.otp_sent:
                    email_input = st.text_input("Enter Email to Login", placeholder="trader@example.com", key="magic_email")
                    st.markdown("<br>", unsafe_allow_html=True)
                    
                    st.markdown("<div class='glow-btn'>", unsafe_allow_html=True)
                    if st.button("📩 Send Magic Link", use_container_width=True, key="btn_send_magic"):
                        if email_input:
                            try:
                                import secrets
                                import hashlib
                                import base64
                                
                                # Generate a cryptographically secure code verifier for PKCE
                                code_verifier = secrets.token_urlsafe(64)
                                
                                # Hash the verifier using SHA-256 to create the challenge
                                digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
                                code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
                                
                                # Build the dynamic redirect URL containing the email and verifier query parameters
                                redirect_to = f"{APP_URL}?email={email_input}&verifier={code_verifier}"
                                
                                # Request Magic Link OTP directly via GoTrue REST API with code challenge
                                headers = {
                                    "apikey": SUPABASE_KEY,
                                    "Authorization": f"Bearer {SUPABASE_KEY}",
                                    "Content-Type": "application/json"
                                }
                                body = {
                                    "email": email_input,
                                    "gotrue_meta_security": {},
                                    "code_challenge": code_challenge,
                                    "code_challenge_method": "s256"
                                }
                                
                                api_url = f"{SUPABASE_URL.rstrip('/')}/auth/v1/otp"
                                resp = requests.post(api_url, headers=headers, json=body, params={"redirect_to": redirect_to}, timeout=15)
                                
                                if resp.status_code != 200:
                                    try:
                                        err_msg = resp.json().get("msg", resp.text)
                                    except Exception:
                                        err_msg = resp.text
                                    raise Exception(f"GoTrue API Error: {err_msg}")
                                
                                # Capture the code verifier and store globally
                                st._pending_verifiers[email_input] = code_verifier
                                
                                st.session_state.login_email = email_input
                                st.session_state.otp_sent = True
                                st.success(f"Link sent successfully!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Failed to send link: {e}")
                        else:
                            st.warning("Please enter a valid email address.")
                    st.markdown("</div>", unsafe_allow_html=True)
                else:
                    st.markdown("<h3 style='color:#ffffff; font-size:1.3rem; font-weight:700;'>🔮 Link Dispatched!</h3>", unsafe_allow_html=True)
                    st.markdown(f"<p style='color:#a1a1aa; font-size:0.85rem;'>A secure magic login link has been sent to <b>{st.session_state.login_email}</b> (check inbox & spam folder).</p>", unsafe_allow_html=True)
                    st.markdown("<p style='color:#6366f1; font-size:0.85rem; font-weight:600;'>Click the link in the email to automatically unlock this terminal!</p>", unsafe_allow_html=True)
                    st.markdown("<br>", unsafe_allow_html=True)
                    
                    if st.button("⬅️ Back / Change Email", use_container_width=True, key="btn_back_magic"):
                        st.session_state.otp_sent = False
                        st.rerun()

            with auth_tab2:
                pwd_email = st.text_input("Email", placeholder="trader@example.com", key="pwd_email")
                pwd_password = st.text_input("Password", type="password", placeholder="••••••••", key="pwd_password")
                st.markdown("<br>", unsafe_allow_html=True)
                
                col_login, col_signup = st.columns(2)
                with col_login:
                    st.markdown("<div class='glow-btn'>", unsafe_allow_html=True)
                    if st.button("🔑 Log In", use_container_width=True, key="btn_pwd_login"):
                        if pwd_email and pwd_password:
                            try:
                                res = supabase_client.auth.sign_in_with_password({
                                    "email": pwd_email,
                                    "password": pwd_password
                                })
                                if res.user:
                                    st.session_state.supabase_user = res.user
                                    st.query_params["rt"] = res.session.refresh_token
                                    st.success("Logged in successfully!")
                                    st.rerun()
                            except Exception as e:
                                st.error(f"Login failed: {e}")
                        else:
                            st.warning("Please enter both email and password.")
                    st.markdown("</div>", unsafe_allow_html=True)
                with col_signup:
                    st.markdown("<div class='glow-btn'>", unsafe_allow_html=True)
                    if st.button("📝 Sign Up", use_container_width=True, key="btn_pwd_signup"):
                        if pwd_email and pwd_password:
                            try:
                                res = supabase_client.auth.sign_up({
                                    "email": pwd_email,
                                    "password": pwd_password
                                })
                                if res.user:
                                    if res.session:
                                        st.session_state.supabase_user = res.user
                                        st.query_params["rt"] = res.session.refresh_token
                                        st.success("Account created and logged in successfully!")
                                        st.rerun()
                                    else:
                                        st.info("Registration successful! Please check your email to confirm your account.")
                            except Exception as e:
                                st.error(f"Sign Up failed: {e}")
                        else:
                            st.warning("Please enter both email and password.")
                    st.markdown("</div>", unsafe_allow_html=True)

            st.markdown("</div>", unsafe_allow_html=True)
            
            # Show SQL editor copy-paste SQL details for setup help
            st.markdown("<br><br>", unsafe_allow_html=True)
            with st.expander("🛠️ Admin: Database Schema Setup Helper"):
                st.markdown("""
                Run this SQL in your Supabase SQL Editor to create the signals table:
                ```sql
                create table signals (
                  id text primary key,
                  time timestamp with time zone,
                  pair text,
                  timeframe text,
                  type text,
                  entry_price double precision,
                  exit_time timestamp with time zone,
                  exit_price double precision,
                  status text,
                  strength text,
                  confirmations text,
                  patterns text
                );
                
                -- Enable Row Level Security (RLS)
                alter table signals enable row level security;
                create policy \"Allow public select\" on signals for select using (true);
                create policy \"Allow public insert\" on signals for insert with check (true);
                create policy \"Allow public update\" on signals for update using (true);
                ```
                """)
        st.stop()
else:
    # Supabase Url / Key configuration instruction screen
    st.title("🔐 Connected Database Credentials Required")
    st.warning("Please connect the scanner app to Supabase to enable secure login sessions and 24/7 background signal logging.")
    
    col_l, col_mid, col_r = st.columns([1, 2, 1])
    with col_mid:
        st.markdown("""
        ### Setup Instructions:
        1. Sign up/Log in to **[supabase.com](https://supabase.com)**.
        2. Create a new project (it's 100% free).
        3. Go to your **Project Settings > API**.
        4. Copy your **Project URL** and the **anon public key**.
        5. Open the **`.env`** file inside your project folder and replace the values:
           ```env
           SUPABASE_URL=https://your-project-id.supabase.co
           SUPABASE_KEY=your-anon-key-here
           ```
        6. Go to **SQL Editor** in Supabase, create a new query, paste this table creation script, and click **Run**:
           ```sql
           create table signals (
             id text primary key,
             time timestamp with time zone,
             pair text,
             timeframe text,
             type text,
             entry_price double precision,
             exit_time timestamp with time zone,
             exit_price double precision,
             status text,
             strength text,
             confirmations text,
             patterns text
           );
           
           alter table signals enable row level security;
           create policy \"Allow public select\" on signals for select using (true);
           create policy \"Allow public insert\" on signals for insert with check (true);
           create policy \"Allow public update\" on signals for update using (true);
           ```
        7. Save the `.env` file and **restart** your Streamlit app in PowerShell!
        """)
    st.stop()

# Tickers & Pairs list - Expanded to include all major currency pairs, cryptos, and commodities
RADAR_PAIRS = [
    # Forex Majors
    "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X", "USDCHF=X", "EURGBP=X", "EURJPY=X", "GBPJPY=X",
    # Forex Minors
    "AUDCAD=X", "AUDCHF=X", "AUDJPY=X", "AUDNZD=X", "EURAUD=X", "EURCAD=X", "EURCHF=X", "GBPAUD=X", "GBPCAD=X", "NZDUSD=X",
    # Cryptocurrencies
    "BTC-USD", "ETH-USD", "LTC-USD",
    # Commodities
    "GC=F", "SI=F", "CL=F",
    # Synthetic Indices (Deriv Only)
    "VOL_10", "VOL_25", "VOL_50", "VOL_75", "VOL_100",
    "VOL_10_1S", "VOL_25_1S", "VOL_50_1S", "VOL_75_1S", "VOL_100_1S",
    "CRASH_300", "BOOM_300", "CRASH_500", "BOOM_500", "CRASH_1000", "BOOM_1000"
]

# Tier-Based Pair Matrix
TIER_1_PAIRS = ["EURUSD=X", "GBPUSD=X", "EURJPY=X"]
TIER_2_PAIRS = [p for p in RADAR_PAIRS if p not in TIER_1_PAIRS]

# Scaled volatility thresholds lookup
ATR_THRESHOLDS = {
    # Forex Majors
    "EURUSD=X": 0.00005,
    "GBPUSD=X": 0.00005,
    "USDJPY=X": 0.01,
    "AUDUSD=X": 0.00005,
    "USDCAD=X": 0.00005,
    "USDCHF=X": 0.00005,
    "EURGBP=X": 0.00005,
    "EURJPY=X": 0.01,
    "GBPJPY=X": 0.01,
    
    # Forex Minors
    "AUDCAD=X": 0.00005,
    "AUDCHF=X": 0.00005,
    "AUDJPY=X": 0.01,
    "AUDNZD=X": 0.00005,
    "EURAUD=X": 0.00005,
    "EURCAD=X": 0.00005,
    "EURCHF=X": 0.00005,
    "GBPAUD=X": 0.00005,
    "GBPCAD=X": 0.00005,
    "NZDUSD=X": 0.00005,
    
    # Cryptocurrencies
    "BTC-USD": 5.0,
    "ETH-USD": 0.5,
    "LTC-USD": 0.05,
    
    # Commodities
    "GC=F": 0.1,
    "SI=F": 0.005,
    "CL=F": 0.05,
    
    # Synthetic Indices
    "VOL_10": 0.005,
    "VOL_25": 0.005,
    "VOL_50": 0.005,
    "VOL_75": 0.005,
    "VOL_100": 0.005,
    "VOL_10_1S": 0.005,
    "VOL_25_1S": 0.005,
    "VOL_50_1S": 0.005,
    "VOL_75_1S": 0.005,
    "VOL_100_1S": 0.005,
    "CRASH_300": 0.005,
    "BOOM_300": 0.005,
    "CRASH_500": 0.005,
    "BOOM_500": 0.005,
    "CRASH_1000": 0.005,
    "BOOM_1000": 0.005
}

# ----------------- NEWS FILTER MODULE -----------------
NEWS_CACHE_FILE = "news_cache.json"

def fetch_weekly_news():
    now = time.time()
    if st.session_state.news_cached_data and (now - st.session_state.news_last_fetched < 3600):
        return st.session_state.news_cached_data
        
    if os.path.exists(NEWS_CACHE_FILE):
        mtime = os.path.getmtime(NEWS_CACHE_FILE)
        if now - mtime < 3600:
            try:
                with open(NEWS_CACHE_FILE, "r") as f:
                    data = json.load(f)
                    st.session_state.news_cached_data = data
                    st.session_state.news_last_fetched = now
                    return data
            except Exception:
                pass

    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            with open(NEWS_CACHE_FILE, "w") as f:
                json.dump(data, f)
            st.session_state.news_cached_data = data
            st.session_state.news_last_fetched = now
            return data
    except Exception:
        pass

    if os.path.exists(NEWS_CACHE_FILE):
        try:
            with open(NEWS_CACHE_FILE, "r") as f:
                data = json.load(f)
                st.session_state.news_cached_data = data
                st.session_state.news_last_fetched = now
                return data
        except Exception:
            pass
    return []

def check_news_block(pair):
    currencies = []
    clean_pair = pair.replace("=X", "").replace("-", "")
    for cur in ["EUR", "USD", "GBP", "JPY", "AUD", "CAD", "CHF"]:
        if cur in clean_pair:
            currencies.append(cur)
    if not currencies:
        currencies = ["USD"]

    news = fetch_weekly_news()
    now_utc = datetime.datetime.now(pytz.utc)
    blocked = False
    active_news_events = []

    for event in news:
        if event.get("country") in currencies and event.get("impact") == "High":
            event_date_str = event.get("date")
            if not event_date_str:
                continue
            try:
                event_time = pd.to_datetime(event_date_str).to_pydatetime()
                if event_time.tzinfo is None:
                    event_time = pytz.utc.localize(event_time)
                else:
                    event_time = event_time.astimezone(pytz.utc)

                time_diff = (now_utc - event_time).total_seconds()
                if abs(time_diff) <= 300:
                    blocked = True
                    active_news_events.append({
                        "title": event.get("title"),
                        "country": event.get("country"),
                        "time": event_time.astimezone(pytz.timezone("Asia/Riyadh")).strftime("%I:%M %p AST")
                    })
            except Exception:
                continue
    return blocked, active_news_events

# ----------------- SESSION FILTER MODULE -----------------
def check_session_filter(enabled=True):
    if not enabled:
        return True, ""
    
    ast_tz = pytz.timezone('Asia/Riyadh')
    now_ast = datetime.datetime.now(ast_tz)
    current_time = now_ast.time()
    
    start_time = datetime.time(10, 0)
    end_time = datetime.time(22, 0)
    
    in_session = start_time <= current_time < end_time
    time_str = now_ast.strftime("%I:%M %p AST")
    
    return in_session, f"Current AST: {time_str} (Bot scans only: 10:00 AM - 10:00 PM AST)"

# ----------------- TECHNICAL INDICATORS MODULE -----------------
def calculate_atr(df, period=14):
    high = df['High']
    low = df['Low']
    close_prev = df['Close'].shift(1)
    
    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low - close_prev).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(window=period).mean()
    
    df['ATR_MA'] = df['ATR'].rolling(window=20).mean()
    df['Low_Volatility'] = df['ATR'] < (df['ATR_MA'] * 0.60)
    return df

def detect_patterns(df):
    body = (df['Close'] - df['Open']).abs()
    rng = df['High'] - df['Low']
    rng = rng.replace(0, 0.00001)
    
    df['Pattern_Doji'] = body <= (rng * 0.10)
    df['Pattern_Marubozu'] = body >= (rng * 0.90)
    
    df['Pattern_Bullish_Engulfing'] = (
        (df['Close'].shift(1) < df['Open'].shift(1)) & 
        (df['Close'] > df['Open']) & 
        (df['Close'] > df['Open'].shift(1)) & 
        (df['Open'] < df['Close'].shift(1))
    )
    df['Pattern_Bearish_Engulfing'] = (
        (df['Close'].shift(1) > df['Open'].shift(1)) & 
        (df['Close'] < df['Open']) & 
        (df['Close'] < df['Open'].shift(1)) & 
        (df['Open'] > df['Close'].shift(1))
    )
    
    lower_shadow = df[['Open', 'Close']].min(axis=1) - df['Low']
    upper_shadow = df['High'] - df[['Open', 'Close']].max(axis=1)
    
    df['Pattern_Hammer'] = (
        (body <= rng * 0.3) & 
        (lower_shadow >= body * 2) & 
        (upper_shadow <= rng * 0.15)
    )
    df['Pattern_Shooting_Star'] = (
        (body <= rng * 0.3) & 
        (upper_shadow >= body * 2) & 
        (lower_shadow <= rng * 0.15)
    )
    
    df['Pattern_3Soldiers'] = (
        (df['Close'] > df['Open']) & 
        (df['Close'].shift(1) > df['Open'].shift(1)) & 
        (df['Close'].shift(2) > df['Open'].shift(2)) & 
        (df['Close'] > df['Close'].shift(1)) & 
        (df['Close'].shift(1) > df['Close'].shift(2)) & 
        (df['Open'] > df['Open'].shift(1)) & 
        (df['Open'].shift(1) > df['Open'].shift(2))
    )
    df['Pattern_3Crows'] = (
        (df['Close'] < df['Open']) & 
        (df['Close'].shift(1) < df['Open'].shift(1)) & 
        (df['Close'].shift(2) < df['Open'].shift(2)) & 
        (df['Close'] < df['Close'].shift(1)) & 
        (df['Close'].shift(1) < df['Close'].shift(2)) & 
        (df['Open'] < df['Open'].shift(1)) & 
        (df['Open'].shift(1) < df['Open'].shift(2))
    )
    
    def get_pattern_label(row):
        labels = []
        if row['Pattern_Bullish_Engulfing']: labels.append("Bullish Engulfing")
        elif row['Pattern_Bearish_Engulfing']: labels.append("Bearish Engulfing")
        if row['Pattern_Hammer']: labels.append("Hammer/Pinbar")
        elif row['Pattern_Shooting_Star']: labels.append("Shooting Star/Pinbar")
        if row['Pattern_Doji']: labels.append("Doji")
        if row['Pattern_Marubozu']: labels.append("Marubozu")
        if row['Pattern_3Soldiers']: labels.append("3 Soldiers")
        if row['Pattern_3Crows']: labels.append("3 Crows")
        return ", ".join(labels) if labels else ""
        
    df['Pattern_Label'] = df.apply(get_pattern_label, axis=1)
    return df

def calculate_indicators(df):
    if len(df) < 50:
        return df

    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['EMA_200'] = df['Close'].ewm(span=200, adjust=False).mean()
    
    delta = df['Close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    ema_gain = gain.ewm(com=13, adjust=False).mean()
    ema_loss = loss.ewm(com=13, adjust=False).mean()
    ema_loss = ema_loss.replace(0, 0.00001)
    rs = ema_gain / ema_loss
    df['RSI_14'] = 100 - (100 / (1 + rs))
    
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
    
    df['BB_Middle'] = df['Close'].rolling(window=20).mean()
    df['BB_Std'] = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['BB_Middle'] + 2 * df['BB_Std']
    df['BB_Lower'] = df['BB_Middle'] - 2 * df['BB_Std']
    
    df['Support'] = df['Low'].rolling(window=50).min()
    df['Resistance'] = df['High'].rolling(window=50).max()
    
    df = calculate_atr(df)
    df = detect_patterns(df)
    
    df['EMA_200_Slope'] = df['EMA_200'].diff(periods=1)
    df['Swing_Low_20'] = df['Low'].rolling(window=20).min()
    df['Swing_High_20'] = df['High'].rolling(window=20).max()
    df['Candle_Range'] = (df['High'] - df['Low']).abs()
    df['ATR_Spike'] = df['Candle_Range'] > (df['ATR'] * 2.5)
    
    return df

# ----------------- SIGNALS & CONFIRMATIONS MODULE -----------------
def check_signals(df, pair=None):
    if len(df) < 50:
        df['Call_Score'] = 0
        df['Put_Score'] = 0
        return df

    macd = df['MACD']
    signal = df['MACD_Signal']
    macd_prev = macd.shift(1)
    signal_prev = signal.shift(1)
    
    # 1. Triggers (Cross-overs and BB Touches)
    macd_up_cross = (macd_prev <= signal_prev) & (macd > signal)
    macd_down_cross = (macd_prev >= signal_prev) & (macd < signal)
    
    bb_lower_touch = (df['Low'].shift(1) <= df['BB_Lower'].shift(1)) | (df['Low'] <= df['BB_Lower'])
    bb_lower_recover = df['Close'] > df['Open']
    bb_call_trigger = bb_lower_touch & bb_lower_recover
    
    bb_upper_touch = (df['High'].shift(1) >= df['BB_Upper'].shift(1)) | (df['High'] >= df['BB_Upper'])
    bb_upper_recover = df['Close'] < df['Open']
    bb_put_trigger = bb_upper_touch & bb_upper_recover
    
    # 2. Safety Filters (RSI Overbought/Oversold boundaries)
    rsi = df['RSI_14']
    call_safe = (rsi < 65) & (df['Close'] > df['EMA_200'])
    put_safe = (rsi > 35) & (df['Close'] < df['EMA_200'])
    
    # 3. Trend Alignment Confirmations
    ema_trend_call = (df['Close'] > df['EMA_50']) | (df['EMA_50'] > df['EMA_200'])
    ema_trend_put = (df['Close'] < df['EMA_50']) | (df['EMA_50'] < df['EMA_200'])
    
    # 4. Volume Confirmations
    vol = df['Volume']
    vol_prev = vol.shift(1)
    if (vol == 0).all():
        vol_increasing = pd.Series(True, index=df.index)
    else:
        vol_increasing = vol > vol_prev
    
    # 5. RSI Room to grow
    rsi_room_call = rsi < 45
    rsi_room_put = rsi > 55
    
    # 6. Calculate Scores (Requires at least one primary trigger + safety + confirmations + V4 Sniper Filters)
    call_scores = []
    put_scores = []
    
    for idx in df.index:
        c_score = 0
        p_score = 0
        
        # Pips multiplier for Pivot filter
        is_jpy = False
        if pair and "JPY" in str(pair):
            is_jpy = True
        pips_mult = 0.01 if is_jpy else 0.0001
        ten_pips = 10 * pips_mult
        
        # V4 Sniper Filters inputs
        ema_slope = df.loc[idx, 'EMA_200_Slope'] if 'EMA_200_Slope' in df.columns else 0.0
        rsi_val = df.loc[idx, 'RSI_14']
        atr_spike = df.loc[idx, 'ATR_Spike'] if 'ATR_Spike' in df.columns else False
        swing_low = df.loc[idx, 'Swing_Low_20'] if 'Swing_Low_20' in df.columns else 0.0
        swing_high = df.loc[idx, 'Swing_High_20'] if 'Swing_High_20' in df.columns else 0.0
        bb_lower = df.loc[idx, 'BB_Lower']
        bb_upper = df.loc[idx, 'BB_Upper']
        
        # CALL SCORE (Strict V4.2 Sniper Logic)
        if call_safe[idx] and macd_up_cross[idx] and bb_lower_touch[idx] and vol_increasing[idx]:
            # Enforce 4 V4 Sniper Filters
            v4_filters_ok = (
                (ema_slope > 0) and
                (40 <= rsi_val <= 55) and
                (not atr_spike) and
                (abs(bb_lower - swing_low) <= ten_pips)
            )
            
            if v4_filters_ok:
                confirmations = 2  # MACD and Bollinger Band touches are both true
                if ema_trend_call[idx]:
                    confirmations += 1
                if vol_increasing[idx]:
                    confirmations += 1
                if rsi_room_call[idx]:
                    confirmations += 1
                
                # Must meet all confirmations to reach exactly Score 5
                if confirmations >= 5:
                    c_score = 5
                
        # PUT SCORE (Strict V4.2 Sniper Logic)
        if put_safe[idx] and macd_down_cross[idx] and bb_upper_touch[idx] and vol_increasing[idx]:
            # Enforce 4 V4 Sniper Filters
            v4_filters_ok = (
                (ema_slope < 0) and
                (45 <= rsi_val <= 60) and
                (not atr_spike) and
                (abs(bb_upper - swing_high) <= ten_pips)
            )
            
            if v4_filters_ok:
                confirmations = 2  # MACD and Bollinger Band touches are both true
                if ema_trend_put[idx]:
                    confirmations += 1
                if vol_increasing[idx]:
                    confirmations += 1
                if rsi_room_put[idx]:
                    confirmations += 1
                
                # Must meet all confirmations to reach exactly Score 5
                if confirmations >= 5:
                    p_score = 5
                    
        call_scores.append(c_score)
        put_scores.append(p_score)
        
    df['Call_Score'] = call_scores
    df['Put_Score'] = put_scores
    return df

# ----------------- TELEGRAM NOTIFICATIONS -----------------
def send_telegram_alert(token, chat_id, text):
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass

# ----------------- BEEP COMPONENT -----------------
def trigger_browser_beep():
    beep_html = """
    <script>
    try {
        var context = new (window.AudioContext || window.webkitAudioContext)();
        var osc = context.createOscillator();
        var gain = context.createGain();
        osc.connect(gain);
        gain.connect(context.destination);
        osc.type = 'sine';
        osc.frequency.setValueAtTime(880, context.currentTime); // High pitch A5
        gain.gain.setValueAtTime(0.15, context.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, context.currentTime + 0.35);
        osc.start();
        osc.stop(context.currentTime + 0.35);
    } catch(e) {
        console.log("AudioContext failed: ", e);
    }
    </script>
    """
    st.components.v1.html(beep_html, height=0, width=0)

# ----------------- AUTO RESULTS EVALUATION -----------------
# ----------------- AUTO RESULTS EVALUATION -----------------
def evaluate_pending_signals(df_live, active_pair):
    for sig in st.session_state.signal_history:
        if sig["status"] == "PENDING" and sig["pair"] == active_pair:
            now_utc = datetime.datetime.now(pytz.utc)
            exit_time_utc = sig["exit_time"].tz_convert(pytz.utc) if sig["exit_time"].tzinfo else pytz.utc.localize(sig["exit_time"])
            
            if now_utc > exit_time_utc:
                if df_live is not None and not df_live.empty:
                    try:
                        target_time = sig["exit_time"]
                        if target_time in df_live.index:
                            exit_price = float(df_live.loc[target_time]['Close'])
                            sig["exit_price"] = exit_price
                            entry_price = sig["entry_price"]
                            
                            if sig["type"] == "CALL":
                                if exit_price > entry_price:
                                    sig["status"] = "WIN"
                                elif exit_price < entry_price:
                                    sig["status"] = "LOSS"
                                    st.session_state.daily_losses += 1
                                else:
                                    sig["status"] = "TIE"
                            elif sig["type"] == "PUT":
                                if exit_price < entry_price:
                                    sig["status"] = "WIN"
                                elif exit_price > entry_price:
                                    sig["status"] = "LOSS"
                                    st.session_state.daily_losses += 1
                                else:
                                    sig["status"] = "TIE"
                            update_signal_in_db(sig)
                        elif (now_utc - exit_time_utc).total_seconds() > 300:
                            # Fallback: exit candle closed but not found in index, resolve with closest index
                            closest_idx = df_live.index.get_indexer([target_time], method='nearest')[0]
                            exit_price = float(df_live.iloc[closest_idx]['Close'])
                            sig["exit_price"] = exit_price
                            entry_price = sig["entry_price"]
                            if sig["type"] == "CALL":
                                sig["status"] = "WIN" if exit_price > entry_price else ("LOSS" if exit_price < entry_price else "TIE")
                            else:
                                sig["status"] = "WIN" if exit_price < entry_price else ("LOSS" if exit_price > entry_price else "TIE")
                            if sig["status"] == "LOSS":
                                st.session_state.daily_losses += 1
                            update_signal_in_db(sig)
                    except Exception:
                        pass

# ----------------- MARKET RADAR DASHBOARD MODULE -----------------
@st.cache_data(ttl=300)
def calculate_radar_data():
    radar_results = {}
    try:
        # Batch download 15m data for all tickers (5d is plenty for EMA 200)
        df_batch = download_market_batch(RADAR_PAIRS, "15m", period="5d")
        if df_batch.empty:
            return radar_results

        for pair in RADAR_PAIRS:
            try:
                # Extract ticker subset
                if len(RADAR_PAIRS) > 1 and pair in df_batch.columns.get_level_values(0):
                    df_pair = df_batch[pair].dropna(subset=['Close'])
                else:
                    df_pair = df_batch.dropna(subset=['Close'])
                
                if len(df_pair) >= 50:
                    # 15m Trend Calculation
                    ema50 = df_pair['Close'].ewm(span=50, adjust=False).mean()
                    ema200 = df_pair['Close'].ewm(span=200, adjust=False).mean()
                    
                    trend_val = "NEUTRAL"
                    if ema50.iloc[-2] > ema200.iloc[-2]:
                        trend_val = "UP"
                    elif ema50.iloc[-2] < ema200.iloc[-2]:
                        trend_val = "DOWN"
                        
                    # ATR 14 Calculation
                    high = df_pair['High']
                    low = df_pair['Low']
                    close_prev = df_pair['Close'].shift(1)
                    tr1 = high - low
                    tr2 = (high - close_prev).abs()
                    tr3 = (low - close_prev).abs()
                    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                    atr14 = tr.rolling(window=14).mean().iloc[-2]
                    
                    thresh = ATR_THRESHOLDS.get(pair, 1.0)
                    
                    status = "WAIT"
                    if atr14 > thresh and trend_val in ["UP", "DOWN"]:
                        status = "TRADE NOW"
                        
                    radar_results[pair] = {
                        "trend": trend_val,
                        "atr": atr14,
                        "status": status
                    }
            except Exception:
                radar_results[pair] = {"trend": "ERROR", "atr": 0.0, "status": "WAIT"}
    except Exception:
        pass
    return radar_results

# ----------------- BACKTEST MODULE -----------------
def run_backtest(pair, timeframe):
    days = 7 if timeframe == "1m" else 30
    st.info(f"Running backtest for {pair} on {timeframe} timeframe over the past {days} days...")
    
    try:
        df = download_market_data(pair, timeframe, period=f"{days}d", count=10000)
        if df.empty:
            st.error("Failed to load historical backtest data.")
            return
            
        df = calculate_indicators(df)
        df = check_signals(df, pair)
        
        df_15m = download_market_data(pair, "15m", period=f"{days}d", count=5000)
        df_15m['EMA_50_15m'] = df_15m['Close'].ewm(span=50, adjust=False).mean()
        df_15m['EMA_200_15m'] = df_15m['Close'].ewm(span=200, adjust=False).mean()
        df_15m['Trend_15m'] = np.where(df_15m['EMA_50_15m'] > df_15m['EMA_200_15m'], "UP", "DOWN")
        
        df_15m_resampled = df_15m['Trend_15m'].reindex(df.index, method='ffill').fillna("NEUTRAL")
        df['Trend_15m'] = df_15m_resampled
        
        wins = 0
        losses = 0
        ties = 0
        backtest_signals = []
        
        for i in range(50, len(df) - 1):
            row = df.iloc[i]
            next_row = df.iloc[i+1]
            
            sig_type = None
            confirmations = 0
            
            # Determine score threshold based on pair Tier
            min_score = 4 if pair in TIER_1_PAIRS else 5
            
            if row['Call_Score'] >= min_score:
                sig_type = "CALL"
                confirmations = row['Call_Score']
            elif row['Put_Score'] >= min_score:
                sig_type = "PUT"
                confirmations = row['Put_Score']
                
            if sig_type:
                if row['Low_Volatility']:
                    continue
                entry_price = row['Close']
                exit_price = next_row['Close']
                pattern = row['Pattern_Label']
                strength = "NORMAL"
                
                mtf_t = row['Trend_15m']
                if (sig_type == "CALL" and mtf_t == "UP") or (sig_type == "PUT" and mtf_t == "DOWN"):
                    strength = "STRONG++"
                elif pattern:
                    strength = "STRONG"
                    
                status = "PENDING"
                if sig_type == "CALL":
                    if exit_price > entry_price:
                        status = "WIN"
                        wins += 1
                    elif exit_price < entry_price:
                        status = "LOSS"
                        losses += 1
                    else:
                        status = "TIE"
                        ties += 1
                else:
                    if exit_price < entry_price:
                        status = "WIN"
                        wins += 1
                    elif exit_price > entry_price:
                        status = "LOSS"
                        losses += 1
                    else:
                        status = "TIE"
                        losses += 1
                        ties += 1
                        
                backtest_signals.append({
                    "Time": df.index[i].strftime("%Y-%m-%d %I:%M %p"),
                    "Type": sig_type,
                    "Strength": strength,
                    "Confirmations": f"{confirmations}/5",
                    "Entry": f"{entry_price:.5f}",
                    "Exit": f"{exit_price:.5f}",
                    "Status": status
                })
                
        total = wins + losses
        winrate = (wins / total) * 100 if total > 0 else 0
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown(f"<div class='metric-card'><div class='metric-title'>Total Signals</div><div class='metric-value'>{total}</div></div>", unsafe_allow_html=True)
        with col2:
            st.markdown(f"<div class='metric-card'><div class='metric-title'>Wins ✅</div><div class='metric-value' style='color:#4caf50;'>{wins}</div></div>", unsafe_allow_html=True)
        with col3:
            st.markdown(f"<div class='metric-card'><div class='metric-title'>Losses ❌</div><div class='metric-value' style='color:#f44336;'>{losses}</div></div>", unsafe_allow_html=True)
        with col4:
            st.markdown(f"<div class='metric-card'><div class='metric-title'>Winrate %</div><div class='metric-value' style='color:#2196f3;'>{winrate:.2f}%</div></div>", unsafe_allow_html=True)
            
        st.markdown("### 📋 Backtest Signal Log")
        if backtest_signals:
            html_table = """
            <table style="width:100%; border-collapse: collapse; text-align: left; background-color: #111827; color:#e5e7eb; border-radius: 8px; overflow: hidden;">
                <thead>
                    <tr style="background-color: #1f2937; border-bottom: 2px solid #374151;">
                        <th style="padding: 12px 16px;">Signal Time</th>
                        <th style="padding: 12px 16px;">Type</th>
                        <th style="padding: 12px 16px;">Strength</th>
                        <th style="padding: 12px 16px;">Confirmations</th>
                        <th style="padding: 12px 16px;">Entry Price</th>
                        <th style="padding: 12px 16px;">Exit Price</th>
                        <th style="padding: 12px 16px;">Status</th>
                    </tr>
                </thead>
                <tbody>
            """
            for sig in reversed(backtest_signals):
                badge_type = f"<span class='badge badge-call'>CALL</span>" if sig["Type"] == "CALL" else f"<span class='badge badge-put'>PUT</span>"
                badge_status = ""
                if sig["Status"] == "WIN":
                    badge_status = "<span class='badge badge-win'>WIN</span>"
                elif sig["Status"] == "LOSS":
                    badge_status = "<span class='badge badge-loss'>LOSS</span>"
                else:
                    badge_status = "<span class='badge badge-tie'>TIE</span>"
                strength_color = "#38bdf8" if sig["Strength"] == "STRONG++" else ("#facc15" if sig["Strength"] == "STRONG" else "#94a3b8")
                
                html_table += f"""<tr style="border-bottom: 1px solid #374151;">
<td style="padding: 10px 16px;">{sig["Time"]}</td>
<td style="padding: 10px 16px;">{badge_type}</td>
<td style="padding: 10px 16px; color: {strength_color}; font-weight: 600;">{sig["Strength"]}</td>
<td style="padding: 10px 16px;">{sig["Confirmations"]}</td>
<td style="padding: 10px 16px;">{sig["Entry"]}</td>
<td style="padding: 10px 16px;">{sig["Exit"]}</td>
<td style="padding: 10px 16px;">{badge_status}</td>
</tr>"""
            html_table += "</tbody></table>"
            st.markdown(html_table, unsafe_allow_html=True)
        else:
            st.write("No signals generated during backtest period.")
    except Exception as e:
        st.error(f"Error during backtesting: {e}")

# ----------------- MAIN UI PIPELINE -----------------

# Initialize / read active pair and timeframe first
active_pair = st.session_state.selected_pair

# Ticker selection dropdown in the sidebar
readable_names = {
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "USDJPY=X": "USD/JPY",
    "AUDUSD=X": "AUD/USD",
    "NZDUSD=X": "NZD/USD",
    "EURGBP=X": "EUR/GBP",
    "GBPJPY=X": "GBP/JPY",
    "EURJPY=X": "EUR/JPY",
    "GC=F": "GOLD (GC=F)",
    "ETH-USD": "ETH/USD",
    "SOL-USD": "SOL/USD"
}

# Determine current selectbox index based on session state
current_index = RADAR_PAIRS.index(active_pair) if active_pair in RADAR_PAIRS else 0
selected_pair_sb = st.sidebar.selectbox(
    "1. SELECT TRADING PAIR",
    options=RADAR_PAIRS,
    format_func=lambda x: readable_names.get(x, x),
    index=current_index
)

# Synchronize sidebar selectbox selection with radar selection
if selected_pair_sb != active_pair:
    st.session_state.selected_pair = selected_pair_sb
    st.rerun()

# Timeframe selection in sidebar
timeframe_map = {"15 Minutes": "15m"}
timeframe_sel = st.sidebar.selectbox("TIMEFRAME SELECT", list(timeframe_map.keys()), index=0)
timeframe = timeframe_map[timeframe_sel]

# Expiry selection (1 to 5 candles)
expiry_candles = st.sidebar.slider("TRADE EXPIRY (CANDLES)", min_value=1, max_value=5, value=1, step=1, help="Select trade duration in terms of number of candles.")

st.sidebar.markdown("### 👁️ CHART TOGGLES")
show_emas = st.sidebar.checkbox("Show EMA 50 & 200", value=True)
show_bb = st.sidebar.checkbox("Show Bollinger Bands", value=True)
show_sr = st.sidebar.checkbox("Show Support/Resistance Lines", value=True)
show_patterns = st.sidebar.checkbox("Show Candlestick Patterns", value=True)

# Cache live data downloads with 15s TTL to prevent rate limit blocks and make pair switching instant
@st.cache_data(ttl=15)
def get_live_data(pair, tf):
    lookback = "2d" if tf == "5m" else ("5d" if tf == "15m" else "1d")
    try:
        df = download_market_data(pair, tf, period=lookback)
        return df
    except Exception:
        return pd.DataFrame()

df_live = get_live_data(active_pair, timeframe)
if not df_live.empty:
    try:
        df_live = calculate_indicators(df_live)
        df_live = check_signals(df_live, active_pair)
    except Exception as e:
        st.error(f"Error calculating indicators: {e}")
else:
    st.error("Failed to load live price data from yfinance.")

# Synchronize signal history from Supabase for the active pair and timeframe on every rerun
if supabase_client is not None and "supabase_user" in st.session_state:
    st.session_state.signal_history = fetch_signals_from_db(active_pair, timeframe)
    
    # Real-time alert triggers on new central signals
    if st.session_state.signal_history:
        latest_sig = st.session_state.signal_history[0]
        latest_sig_id = latest_sig["id"]
        
        # Trigger Confetti if latest signal is a WIN and not already celebrated
        if latest_sig.get("status") == "WIN":
            if "last_confetti_sig_id" not in st.session_state or st.session_state.last_confetti_sig_id != latest_sig_id:
                st.session_state.last_confetti_sig_id = latest_sig_id
                trigger_confetti()
                
        if "last_alerted_signal" not in st.session_state:
            st.session_state.last_alerted_signal = latest_sig_id
            
        if st.session_state.last_alerted_signal != latest_sig_id:
            st.session_state.last_alerted_signal = latest_sig_id
            
            # Double check if the timestamp is very recent (e.g. within 2 minutes)
            sig_time_utc = latest_sig["time"]
            now_utc = datetime.datetime.now(pytz.utc)
            if (now_utc - sig_time_utc).total_seconds() < 120:
                st.toast(f"🔥 NEW CENTRAL SIGNAL DETECTED: {latest_sig['type']} on {latest_sig['pair'].replace('=X','')} [{latest_sig['timeframe']}]!", icon="🔊")
                trigger_browser_beep()

# Calculate live stats from Supabase
today_sigs_count = 0
win_rate = 0.0
if supabase_client is not None:
    try:
        tz_ry = pytz.timezone("Asia/Riyadh")
        now_ry = datetime.datetime.now(tz_ry)
        start_of_day_ry = tz_ry.localize(datetime.datetime(now_ry.year, now_ry.month, now_ry.day, 0, 0, 0))
        start_of_day_utc = start_of_day_ry.astimezone(pytz.utc).isoformat()
        
        res_all = supabase_client.table("signals").select("*").gte("time", start_of_day_utc).execute()
        all_today_sigs = res_all.data if res_all.data else []
        sig_15m = [s for s in all_today_sigs if s["timeframe"].upper() == "15M"]
        today_sigs_count = len(sig_15m)
        
        resolved = [s for s in sig_15m if s["status"] in ["WIN", "LOSS"]]
        wins = sum(1 for s in resolved if s["status"] == "WIN")
        win_rate = (wins / len(resolved) * 100) if resolved else 0.0
    except Exception:
        pass

# Calculate live background thread status
import threading
thread_alive = any(t.name == "scanner_thread_func" for t in threading.enumerate())
thread_badge = '<span class="vip-badge vip-badge-win glow-green">ACTIVE</span>' if thread_alive else '<span class="vip-badge vip-badge-loss">DEAD</span>'

# Calculate current session status (AST)
now_ast = datetime.datetime.now(pytz.timezone("Asia/Riyadh"))
session_type = local_get_session_type(now_ast)
if session_type == "IN-SESSION":
    session_badge = '<span class="vip-badge vip-badge-win glow-green">🟢 IN-SESSION</span>'
else:
    session_badge = '<span class="vip-badge vip-badge-loss">🔴 OFF-SESSION</span>'

# Top Header HTML
now_clock = now_ast.strftime('%I:%M:%S %p')
header_html = f"""
<div class="vip-card" style="display: flex; justify-content: space-between; align-items: center; border-color: rgba(255, 215, 0, 0.3); margin-top: -50px;">
    <div>
        <h1 style="margin: 0; font-size: 2.2rem; font-weight: 800; background: linear-gradient(90deg, #ffd700 0%, #00ff88 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">⚡ BINARY PRO V4.2</h1>
        <span style="font-size: 0.9rem; color: #94a3b8; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase;">VIP SNIPER TRADING STATION</span>
    </div>
    <div style="display: flex; align-items: center; gap: 15px;">
        <div style="text-align: right;">
            <div style="font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; font-weight: 700;">Live Jeddah Clock</div>
            <div style="font-size: 1.2rem; font-weight: 700; color: #ffffff; font-family: monospace;">{now_clock} AST</div>
        </div>
        {session_badge}
    </div>
</div>
"""
st.markdown(header_html, unsafe_allow_html=True)

# KPI Cards HTML
kpi_html = f"""
<div class="kpi-container">
    <div class="kpi-card kpi-accent-gold">
        <div class="kpi-title">SIGNALS TODAY (15M)</div>
        <div class="kpi-value">{today_sigs_count}</div>
    </div>
    <div class="kpi-card kpi-accent-green">
        <div class="kpi-title">TODAY'S WIN RATE</div>
        <div class="kpi-value">{win_rate:.1f}%</div>
    </div>
    <div class="kpi-card">
        <div class="kpi-title">SCANNER DAEMON</div>
        <div class="kpi-value" style="font-size: 1.5rem; margin-top: 10px;">{thread_badge}</div>
    </div>
</div>
"""
st.markdown(kpi_html, unsafe_allow_html=True)

# Session & News Filters status warning checks (Global Checks)
session_ok, session_msg = check_session_filter(True)
news_blocked = False

# Sidebar inputs for Telegram & Currency converter
st.sidebar.markdown("## ⚙️ GLOBAL VIP OPTIONS")

# Start/Stop Scanner in sidebar
st.sidebar.markdown("---")
col_start, col_stop = st.sidebar.columns(2)
with col_start:
    if st.button("▶️ START", use_container_width=True):
        if st.session_state.daily_losses >= 3:
            st.sidebar.error("Daily loss limit hit!")
        else:
            st.session_state.scanning = True
with col_stop:
    if st.button("⏸️ STOP", use_container_width=True):
        st.session_state.scanning = False

if st.session_state.scanning:
    st.sidebar.success("🟢 SCANNER ACTIVE")
else:
    st.sidebar.warning("🔴 SCANNER PAUSED")

# Data Source Selection
st.sidebar.markdown("---")
st.sidebar.markdown("### 🔌 DATA SOURCE FEED")
current_source = settings_manager.get_active_data_source()
source_options = ["Deriv WebSocket", "yfinance"]
selected_index = source_options.index(current_source) if current_source in source_options else 0
active_source = st.sidebar.selectbox("Active Provider", source_options, index=selected_index)
settings_manager.set_active_data_source(active_source)

# Host Controller Selection
st.sidebar.markdown("---")
st.sidebar.markdown("### 🖥️ ACTIVE HOST CONTROL")
current_host = settings_manager.get_active_host()
host_options = ["Render", "AWS"]
selected_host_index = host_options.index(current_host) if current_host in host_options else 0
active_host = st.sidebar.selectbox("Designated Server", host_options, index=selected_host_index)
settings_manager.set_active_host(active_host)

if active_host == "Render":
    st.sidebar.info("ℹ️ **Render Server** is active. AWS server is in standby.")
else:
    st.sidebar.info("ℹ️ **AWS Server** is active. Render server is in standby.")

# Global Settings
st.sidebar.markdown("---")
st.sidebar.info("🚀 **DUAL MODE 24/7 ACTIVE**\nBot scans and labels both 🟢 IN-SESSION & 🟡 OFF-SESSION signals.")
news_filter_enabled = st.sidebar.checkbox("News Calendar Filter", value=True)
volatility_filter_enabled = st.sidebar.checkbox("Volatility ATR Filter", value=True)



# Telegram Settings Panel
st.sidebar.markdown("---")
st.sidebar.markdown("### ✈️ TELEGRAM ALERTS")

# Load existing values from environment variables to pre-fill the fields
env_tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
env_tg_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

tg_token = st.sidebar.text_input("Bot Token", value=env_tg_token, type="password", help="Telegram Bot Token")
tg_chat_id = st.sidebar.text_input("Chat ID", value=env_tg_chat_id, type="password", help="Telegram Chat ID")

if st.sidebar.button("💾 Save Telegram Settings", use_container_width=True):
    if tg_token and tg_chat_id:
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            env_path = os.path.join(current_dir, ".env")
            
            env_lines = []
            if os.path.exists(env_path):
                with open(env_path, "r") as f:
                    env_lines = f.readlines()
                    
            updated_token = False
            updated_chat = False
            
            for idx, line in enumerate(env_lines):
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    env_lines[idx] = f"TELEGRAM_BOT_TOKEN={tg_token}\n"
                    updated_token = True
                elif line.startswith("TELEGRAM_CHAT_ID="):
                    env_lines[idx] = f"TELEGRAM_CHAT_ID={tg_chat_id}\n"
                    updated_chat = True
                    
            if not updated_token:
                env_lines.append(f"TELEGRAM_BOT_TOKEN={tg_token}\n")
            if not updated_chat:
                env_lines.append(f"TELEGRAM_CHAT_ID={tg_chat_id}\n")
                
            with open(env_path, "w") as f:
                f.writelines(env_lines)
                
            # Immediately update the active environment variables
            os.environ["TELEGRAM_BOT_TOKEN"] = tg_token
            os.environ["TELEGRAM_CHAT_ID"] = tg_chat_id
            
            st.sidebar.success("Saved to local .env config!")
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"Failed to save settings: {e}")
    else:
        st.sidebar.warning("Please fill both Token and Chat ID.")

if st.sidebar.button("🔔 Send Test Message", use_container_width=True):
    if tg_token and tg_chat_id:
        with st.sidebar.spinner("Sending test message..."):
            test_text = "<b>🔔 BINARY PRO SCANNER V4 (SNIPER EDITION)</b>\n\nThis is a test alert to verify your Telegram Bot connection. The bot is working properly! 🟢"
            url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
            payload = {
                "chat_id": tg_chat_id,
                "text": test_text,
                "parse_mode": "HTML"
            }
            try:
                resp = requests.post(url, json=payload, timeout=10)
                if resp.status_code == 200:
                    st.sidebar.success("✅ Test message sent! Check your Telegram.")
                else:
                    err_info = resp.json().get("description", resp.text)
                    st.sidebar.error(f"❌ Telegram Error: {err_info}")
            except Exception as e:
                st.sidebar.error(f"❌ Connection Failed: {e}")
    else:
        st.sidebar.warning("Please fill both Token and Chat ID to test.")

# 📊 Report Generator Sidebar Panel
st.sidebar.markdown("---")
st.sidebar.markdown("### 📊 REPORT GENERATOR")
report_type = st.sidebar.selectbox("Report Interval", ["Today's Summary", "Last 1 Hour Summary", "Specific Date Summary"])

target_date = datetime.date.today()
if report_type == "Specific Date Summary":
    selected_date = st.sidebar.date_input("Select Date", datetime.date.today())
    target_date = selected_date

if st.sidebar.button("🔍 Generate Summary", use_container_width=True):
    if supabase_client is not None:
        with st.sidebar.spinner("Generating summary..."):
            tz_ry = pytz.timezone("Asia/Riyadh")
            if report_type == "Last 1 Hour Summary":
                start_time_ry = datetime.datetime.now(tz_ry) - datetime.timedelta(hours=1)
                start_time_utc = start_time_ry.astimezone(pytz.utc).isoformat()
                res = supabase_client.table("signals").select("*").gte("time", start_time_utc).order("time", desc=True).execute()
                signals = res.data if res.data else []
                report_title = f"HOURLY REPORT ({start_time_ry.strftime('%I:%M %p')} - {datetime.datetime.now(tz_ry).strftime('%I:%M %p')})"
            else:
                # Today or Specific Date
                start_dt = tz_ry.localize(datetime.datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0))
                end_dt = tz_ry.localize(datetime.datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59))
                start_utc = start_dt.astimezone(pytz.utc).isoformat()
                end_utc = end_dt.astimezone(pytz.utc).isoformat()
                res = supabase_client.table("signals").select("*").gte("time", start_utc).lte("time", end_utc).order("time", desc=True).execute()
                signals = res.data if res.data else []
                report_title = f"DAILY REPORT ({target_date.strftime('%Y-%m-%d')})"
                
            if signals:
                # Calculate Stats
                stats = {}
                total_wins = 0
                total_losses = 0
                for tf in ["1m", "5m", "15m"]:
                    tf_sigs = [s for s in signals if s["timeframe"].upper() == tf.upper()]
                    wins = sum(1 for s in tf_sigs if s["status"] == "WIN")
                    losses = sum(1 for s in tf_sigs if s["status"] in ["LOSS", "TIE"])
                    total_wl = wins + losses
                    winrate = (wins / total_wl) * 100 if total_wl > 0 else 0.0
                    stats[tf] = {
                        "wins": wins,
                        "losses": losses,
                        "winrate": winrate,
                        "signals": tf_sigs
                    }
                    total_wins += wins
                    total_losses += losses
                    
                overall_wl = total_wins + total_losses
                overall_winrate = (total_wins / overall_wl) * 100 if overall_wl > 0 else 0.0
                
                report_text = f"📊 <b>{report_title}</b>\n"
                report_text += f"🎯 <b>Overall Accuracy:</b> <b>{overall_winrate:.1f}%</b> ({total_wins}W - {total_losses}L)\n\n"
                
                for tf in ["1m", "5m", "15m"]:
                    tf_disp = "1 Min" if tf == "1m" else ("5 Min" if tf == "5m" else "15 Min")
                    report_text += f"⏱️ <b>{tf_disp} Trades</b> ({stats[tf]['wins']}W - {stats[tf]['losses']}L | {stats[tf]['winrate']:.1f}%):\n"
                    if stats[tf]["signals"]:
                        for sig in stats[tf]["signals"][:15]: # Limit to latest 15 trades per TF to prevent long messages
                            sig_time_utc = pd.to_datetime(sig["time"])
                            if sig_time_utc.tzinfo is None:
                                sig_time_utc = pytz.utc.localize(sig_time_utc)
                            sig_time_ry = sig_time_utc.astimezone(tz_ry)
                            time_str = sig_time_ry.strftime("%I:%M %p")
                            pair_clean = sig["pair"].replace("=X", "").replace("-USD", "/USD")
                            
                            status_emoji = "⏳"
                            if sig["status"] == "WIN":
                                status_emoji = "🟢 WIN"
                            elif sig["status"] == "LOSS":
                                status_emoji = "🔴 LOSS"
                            elif sig["status"] == "TIE":
                                status_emoji = "⚪ TIE"
                            report_text += f"• <code>{time_str}</code> | <b>{pair_clean}</b> | {status_emoji}\n"
                    else:
                        report_text += "<i>No trades triggered.</i>\n"
                    report_text += "\n"
                
                st.session_state.custom_report_text = report_text
                st.session_state.custom_report_title = report_title
                st.session_state.custom_report_ready = True
            else:
                st.sidebar.warning("No signals found for this period.")
                st.session_state.custom_report_ready = False
    else:
        st.sidebar.error("Supabase client is not initialized.")

if "custom_report_ready" in st.session_state and st.session_state.custom_report_ready:
    st.sidebar.info(f"Report generated: {st.session_state.custom_report_title}")
    with st.sidebar.expander("👁️ View Report Preview"):
        st.write(st.session_state.custom_report_text.replace("<b>", "**").replace("</b>", "**").replace("<code>", "`").replace("</code>", "`").replace("<i>", "*").replace("</i>", "*"))
        
    if st.sidebar.button("📤 Send Report to Telegram", use_container_width=True):
        if env_tg_token and env_tg_chat_id:
            with st.sidebar.spinner("Sending report to Telegram..."):
                url = f"https://api.telegram.org/bot{env_tg_token}/sendMessage"
                payload = {
                    "chat_id": env_tg_chat_id,
                    "text": st.session_state.custom_report_text,
                    "parse_mode": "HTML"
                }
                try:
                    resp = requests.post(url, json=payload, timeout=15)
                    if resp.status_code == 200:
                        st.sidebar.success("✅ Report sent to Telegram bot!")
                        st.session_state.custom_report_ready = False
                    else:
                        err = resp.json().get("description", resp.text)
                        st.sidebar.error(f"❌ Telegram Error: {err}")
                except Exception as e:
                    st.sidebar.error(f"❌ Failed to send: {e}")
        else:
            st.sidebar.warning("Configure Bot Token & Chat ID first.")



# Log Out Button
st.sidebar.markdown("---")
if st.sidebar.button("🚪 Log Out", use_container_width=True):
    if supabase_client is not None:
        try:
            supabase_client.auth.sign_out()
        except Exception:
            pass
    if "supabase_user" in st.session_state:
        del st.session_state.supabase_user
    if "db_signals_loaded" in st.session_state:
        st.session_state.db_signals_loaded = False
    st.query_params.pop("rt", None)
    st.rerun()

# Parse query parameters for active pair selection
if "pair" in st.query_params:
    st.session_state.selected_pair = st.query_params["pair"]

# ----------------- HORIZONTAL MARKET RADAR ASSEMBLY -----------------
st.markdown("## 📡 MARKET RADAR")
st.caption("Auto 15m Trend & ATR Volatility Scanner (Landscape Scroll)")

radar_data = calculate_radar_data()
if radar_data:
    # Build a horizontal swipe/scroll layout using custom CSS & HTML (concatenated without leading spaces to prevent markdown code block parsing)
    html_radar = '<div style="display: flex; overflow-x: auto; gap: 12px; padding: 10px 5px; margin-bottom: 25px; scrollbar-width: thin; -webkit-overflow-scrolling: touch;">'
    for pair_ticker in RADAR_PAIRS:
        pair_name = pair_ticker.replace("=X", "").replace("-USD", "/USD")
        pair_info = radar_data.get(pair_ticker, {"trend": "NEUTRAL", "status": "WAIT"})
        
        # Determine highlighting based on selection
        is_selected = pair_ticker == st.session_state.selected_pair
        border_color = "rgba(0, 255, 136, 0.4)" if is_selected else "rgba(255, 255, 255, 0.05)"
        bg_color = "rgba(0, 255, 136, 0.08)" if is_selected else "rgba(20, 20, 45, 0.45)"
        shadow = "box-shadow: 0 0 15px rgba(0, 255, 136, 0.25);" if is_selected else "box-shadow: 0 4px 15px rgba(0,0,0,0.2);"
        backdrop = "backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);"
        
        # Badges
        trend_text = '<span style="color:#00ff88; font-weight:700;">🟢 BULLISH</span>' if pair_info["trend"] == "UP" else ('<span style="color:#ff073a; font-weight:700;">🔴 BEARISH</span>' if pair_info["trend"] == "DOWN" else '<span style="color:#cbd5e1; font-weight:700;">⚪ NEUTRAL</span>')
        status_bg = "linear-gradient(90deg, #00ff88, #00b0ff)" if pair_info["status"] == "TRADE NOW" else "rgba(255, 255, 255, 0.05)"
        status_color = "#050510" if pair_info["status"] == "TRADE NOW" else "#94a3b8"
        
        rt_val = st.query_params.get("rt", "")
        link = f"/?pair={pair_ticker}"
        if rt_val:
            link += f"&rt={rt_val}"
            
        card_html = f'<a href="{link}" target="_self" style="text-decoration: none; color: inherit; display: inline-block;">'
        card_html += f'<div style="background-color: {bg_color}; border: 1px solid {border_color}; padding: 12px; border-radius: 12px; min-width: 140px; text-align: center; {shadow} {backdrop} transition: all 0.3s ease;">'
        card_html += f'<div style="font-weight: 800; font-size: 0.9rem; color: #ffffff; margin-bottom: 6px; letter-spacing:0.05em;">{pair_name}</div>'
        card_html += f'<div style="font-size: 0.75rem; margin-bottom: 8px;">{trend_text}</div>'
        card_html += f'<div style="background: {status_bg}; color: {status_color}; font-size: 0.65rem; font-weight: 800; padding: 4px 10px; border-radius: 20px; display: inline-block; text-transform:uppercase; letter-spacing:0.05em;">{pair_info["status"]}</div>'
        card_html += '</div></a>'
        
        html_radar += card_html
        
    html_radar += "</div>"
    st.markdown(html_radar, unsafe_allow_html=True)
else:
    st.error("Failed to load Market Radar batch data.")

# ----------------- TWO COLUMN LAYOUT ASSEMBLY -----------------
col_center, col_right = st.columns([8, 4])

# CENTER COLUMN - LIVE STATION CHART & BACKTESTER
with col_center:
    active_pair = st.session_state.selected_pair
    st.markdown(f"## 📊 LIVE CHART: **{active_pair.replace('=X','')}**")
    
    # Check session limit
    if session_filter_enabled and not session_ok:
        st.warning(f"☕ SESSION FILTER ACTIVE - BOT IS PAUSED\n\n{session_msg}")
        st.session_state.scanning = False
        
    # Check news filter
    if news_filter_enabled:
        news_blocked, active_news = check_news_block(active_pair)
        if news_blocked:
            st.error(f"🚫 SIGNALS BLOCKED - High Impact News Event!")
            for event in active_news:
                st.markdown(f"- 🚩 **{event['title']}** ({event['country']}) at **{event['time']}**")
                
    # Tab View for Live, TradingView and Backtest
    tab_live, tab_tv, tab_backtest, tab_diag = st.tabs(["📈 STATION CHART (Indicators & Alerts)", "🖥️ TRADINGVIEW WIDGET", "🧪 SYSTEM BACKTEST", "🩺 SYSTEM DIAGNOSTICS"])
    
    with tab_live:
        # Download Active Ticker Live Data
        lookback = "5d" if timeframe.lower() in ["5m", "15m"] else "2d"
        try:
            # df_live has already been downloaded and processed at the top of the pipeline
            if not df_live.empty:
                closed_candle = df_live.iloc[-2]
                closed_candle_time = df_live.index[-2]
                
                # Volatility Check for Active Pair
                volatility_low = False
                if volatility_filter_enabled and closed_candle['Low_Volatility']:
                    volatility_low = True
                    st.warning("⚠️ VOLATILITY WARNING: ATR IS EXTREMELY LOW. SCANNING SUSPENDED.")
                    
                # Current Price metrics
                curr_price = df_live['Close'].iloc[-1]
                p_change = curr_price - df_live['Close'].iloc[-2]
                p_pct = (p_change / df_live['Close'].iloc[-2]) * 100
                
                col_met1, col_met2 = st.columns(2)
                with col_met1:
                    st.metric(label=f"Current Price ({active_pair})", value=f"{curr_price:.5f}", delta=f"{p_change:.5f} ({p_pct:.2f}%)")
                with col_met2:
                    current_radar_info = radar_data.get(active_pair, {"trend": "NEUTRAL", "atr": 0.0})
                    st.metric(label="15m MTF Trend", value=current_radar_info["trend"], delta="Active Pair Trend")
                    
                # Render Multi-plot Plotly Chart with custom Indicators
                fig = make_subplots(
                    rows=4, cols=1,
                    shared_xaxes=True,
                    vertical_spacing=0.03,
                    row_heights=[0.55, 0.15, 0.15, 0.15]
                )
                
                # Candlesticks
                fig.add_trace(
                    go.Candlestick(
                        x=df_live.index,
                        open=df_live['Open'],
                        high=df_live['High'],
                        low=df_live['Low'],
                        close=df_live['Close'],
                        name="Price"
                    ),
                    row=1, col=1
                )
                
                if show_emas:
                    fig.add_trace(go.Scatter(x=df_live.index, y=df_live['EMA_50'], line=dict(color='#ff9800', width=1.5), name="EMA 50"), row=1, col=1)
                    fig.add_trace(go.Scatter(x=df_live.index, y=df_live['EMA_200'], line=dict(color='#9c27b0', width=2.0), name="EMA 200"), row=1, col=1)
                
                if show_bb:
                    fig.add_trace(go.Scatter(x=df_live.index, y=df_live['BB_Upper'], line=dict(color='#1e88e5', width=1, dash='dash'), name="BB Upper"), row=1, col=1)
                    fig.add_trace(go.Scatter(x=df_live.index, y=df_live['BB_Lower'], line=dict(color='#1e88e5', width=1, dash='dash'), name="BB Lower"), row=1, col=1)
                
                if show_sr:
                    sup_val = df_live['Support'].iloc[-1]
                    res_val = df_live['Resistance'].iloc[-1]
                    fig.add_hline(y=sup_val, line=dict(color='#00e676', width=1, dash='dot'), annotation_text=f"Support: {sup_val:.5f}", row=1, col=1)
                    fig.add_hline(y=res_val, line=dict(color='#ff1744', width=1, dash='dot'), annotation_text=f"Resistance: {res_val:.5f}", row=1, col=1)
                
                # Historical arrows overlay
                for sig in st.session_state.signal_history:
                    if sig["pair"] == active_pair and sig["timeframe"].upper() == timeframe.upper():
                        sig_time = sig["time"]
                        if sig_time in df_live.index:
                            price_pt = sig["entry_price"]
                            if sig["type"] == "CALL":
                                fig.add_annotation(
                                    x=sig_time, y=price_pt,
                                    text="▲ CALL", showarrow=True, arrowhead=1,
                                    arrowcolor="#00e676", arrowsize=1.5,
                                    font=dict(color="#00e676", size=12, family="Arial Bold"),
                                    bgcolor="rgba(11, 30, 20, 0.8)", bordercolor="#00e676", borderwidth=1,
                                    row=1, col=1
                                )
                            else:
                                fig.add_annotation(
                                    x=sig_time, y=price_pt,
                                    text="▼ PUT", showarrow=True, arrowhead=1,
                                    arrowcolor="#ff1744", arrowsize=1.5,
                                    font=dict(color="#ff1744", size=12, family="Arial Bold"),
                                    bgcolor="rgba(30, 11, 11, 0.8)", bordercolor="#ff1744", borderwidth=1,
                                    row=1, col=1
                                )
                
                # Patterns label Overlay
                if show_patterns:
                    pattern_df = df_live[df_live['Pattern_Label'] != ""]
                    for idx, row in pattern_df.iterrows():
                        fig.add_annotation(
                            x=idx, y=row['High'],
                            text=row['Pattern_Label'],
                            showarrow=False,
                            font=dict(color="#facc15", size=9),
                            yshift=15,
                            row=1, col=1
                        )
                
                # RSI
                fig.add_trace(go.Scatter(x=df_live.index, y=df_live['RSI_14'], line=dict(color='#fbc02d', width=1.5), name="RSI"), row=2, col=1)
                fig.add_hline(y=70, line=dict(color='#ff1744', width=1, dash='dash'), row=2, col=1)
                fig.add_hline(y=50, line=dict(color='#ffffff', width=0.8, dash='dot'), row=2, col=1)
                fig.add_hline(y=30, line=dict(color='#00e676', width=1, dash='dash'), row=2, col=1)
                
                # MACD
                fig.add_trace(go.Scatter(x=df_live.index, y=df_live['MACD'], line=dict(color='#29b6f6', width=1.2), name="MACD"), row=3, col=1)
                fig.add_trace(go.Scatter(x=df_live.index, y=df_live['MACD_Signal'], line=dict(color='#ab47bc', width=1.2), name="Signal"), row=3, col=1)
                colors_hist = ['#00e676' if val >= 0 else '#ff1744' for val in df_live['MACD_Hist']]
                fig.add_trace(go.Bar(x=df_live.index, y=df_live['MACD_Hist'], marker_color=colors_hist, name="Hist"), row=3, col=1)
                
                # Volume
                colors_vol = ['#00e676' if close >= open_p else '#ff1744' for close, open_p in zip(df_live['Close'], df_live['Open'])]
                fig.add_trace(go.Bar(x=df_live.index, y=df_live['Volume'], marker_color=colors_vol, name="Volume"), row=4, col=1)
                
                fig.update_layout(
                    xaxis_rangeslider_visible=False,
                    height=450,
                    paper_bgcolor='#0b0e14',
                    plot_bgcolor='#0e121a',
                    margin=dict(l=10, r=10, t=10, b=10),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                fig.update_xaxes(gridcolor='#1e293b', zerolinecolor='#1e293b')
                fig.update_yaxes(gridcolor='#1e293b', zerolinecolor='#1e293b')
                st.plotly_chart(fig, use_container_width=True)
                
                if st.session_state.scanning:
                    st.caption("🔄 Auto-refresh active (30s interval)")
            else:
                st.error("Empty data received for active pair.")
        except Exception as e:
            st.error(f"Error drawing Plotly chart: {e}")
            
    with tab_tv:
        # Render TradingView Interactive Widget
        import streamlit.components.v1 as components
        tv_mapping = {
            "EURUSD=X": "FX:EURUSD",
            "GBPUSD=X": "FX:GBPUSD",
            "USDJPY=X": "FX:USDJPY",
            "AUDUSD=X": "FX:AUDUSD",
            "USDCAD=X": "FX:USDCAD",
            "USDCHF=X": "FX:USDCHF",
            "EURGBP=X": "FX:EURGBP",
            "GBPJPY=X": "FX:GBPJPY",
            "BTC-USD": "BINANCE:BTCUSDT",
            "ETH-USD": "BINANCE:ETHUSDT",
            "SOL-USD": "BINANCE:SOLUSDT",
            "GC=F": "OANDA:XAUUSD",
            "CL=F": "NYMEX:CL1!"
        }
        tv_symbol = tv_mapping.get(active_pair, active_pair)
        tv_interval = "1" if timeframe == "1m" else ("5" if timeframe == "5m" else "15")
        
        html_tv = f"""
        <div class="tradingview-widget-container" style="height:500px; width:100%;">
          <div id="tradingview_chart" style="height:470px; width:100%;"></div>
          <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
          <script type="text/javascript">
          new TradingView.widget({{
            "width": "100%",
            "height": 470,
            "symbol": "{tv_symbol}",
            "interval": "{tv_interval}",
            "timezone": "Asia/Riyadh",
            "theme": "dark",
            "style": "1",
            "locale": "en",
            "toolbar_bg": "#f1f3f6",
            "enable_publishing": false,
            "hide_side_toolbar": false,
            "allow_symbol_change": true,
            "save_image": false,
            "container_id": "tradingview_chart",
            "studies": [
              "MASimple@tv-basicstudies",
              "RSI@tv-basicstudies",
              "MACD@tv-basicstudies"
            ]
          }});
          </script>
        </div>
        """
        components.html(html_tv, height=500)
        st.caption("🖥️ Live TradingView Interactive Chart Widget (Timezone: AST/Jeddah)")
            
    with tab_backtest:
        run_backtest(active_pair, timeframe)

    with tab_diag:
        st.subheader("🩺 System Diagnostics Dashboard (V4.2 Sniper)")
        
        # Load env variables for connection tests
        tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        tg_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        
        # 1. Connection Status Check
        st.markdown("### 🔌 CONNECTION STATUS CHECK")
        db_ok = False
        db_msg = "Unknown Error"
        last_sig = None
        if supabase_client is not None:
            try:
                res_db = supabase_client.table("signals").select("*").limit(1).execute()
                db_ok = True
                db_msg = "Connected"
                if res_db.data:
                    last_sig = res_db.data[0]
            except Exception as dbe:
                db_msg = str(dbe)
                
        tg_ok = False
        bot_name = "N/A"
        tg_msg = "Unknown Error"
        if tg_token and tg_chat_id:
            try:
                url_tg = f"https://api.telegram.org/bot{tg_token}/getMe"
                res_tg = requests.get(url_tg, timeout=5)
                if res_tg.status_code == 200:
                    tg_ok = True
                    bot_name = res_tg.json().get("result", {}).get("first_name", "Unknown")
                    tg_msg = "Valid"
                else:
                    tg_msg = f"HTTP Error {res_tg.status_code}: {res_tg.text}"
            except Exception as tge:
                tg_msg = str(tge)
                
        provider_ok = False
        provider_msg = "Unknown Error"
        active_provider = settings_manager.get_active_data_source()
        try:
            df_test = download_market_data("EURUSD=X", "15m", period="1d")
            if not df_test.empty:
                provider_ok = True
                provider_msg = f"Online (Last Close: {float(df_test['Close'].iloc[-1]):.5f})"
            else:
                provider_msg = "Empty DataFrame"
        except Exception as pe:
            provider_msg = str(pe)
            
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Supabase Database", "🟢 Connected" if db_ok else "🔴 Failed", help=db_msg)
            if last_sig:
                st.caption(f"Last Signal: {last_sig['pair']} [{last_sig['timeframe']}] at {last_sig['time'][:16]}")
        with c2:
            st.metric("Telegram Connection", "🟢 Valid" if tg_ok else "🔴 Invalid", f"Bot: {bot_name}", help=tg_msg)
        with c3:
            st.metric("Data Provider Status", "🟢 Online" if provider_ok else "🔴 Offline", f"Active: {active_provider}", help=provider_msg)
            
        # 2. Scanner Thread Status
        st.markdown("### ⚙️ SCANNER THREAD STATUS")
        import threading
        thread_alive = any(t.name == "scanner_thread_func" for t in threading.enumerate())
        
        last_scan_time = SystemHealth.LAST_SCAN_TIME
        now_ast = datetime.datetime.now(pytz.timezone("Asia/Riyadh"))
        session_type = local_get_session_type(now_ast)
        session_label = "🟢 IN-SESSION" if session_type == "IN-SESSION" else "🟡 OFF-SESSION"
        
        s1, s2, s3 = st.columns(3)
        with s1:
            st.metric("Scanner Thread State", "🟢 Running (Alive)" if thread_alive else "🔴 Stopped (Dead)")
        with s2:
            st.metric("Last Scan Event", last_scan_time)
        with s3:
            st.metric("Current Market Session", session_label, help="London + New York overlap: 10AM-10PM AST")
            
        # 3. V4.2 Logic Verifier
        st.markdown("### 🧪 V4.2 STRATEGY LOGIC VERIFIER")
        if st.button("Run Test Signal Logic", use_container_width=True):
            try:
                # Create a mock dataframe
                dates = pd.date_range(start='2026-07-30T10:00:00', periods=60, freq='15min')
                df_test = pd.DataFrame({
                    'Open': [1.08500] * 60,
                    'High': [1.08600] * 60,
                    'Low': [1.08400] * 60,
                    'Close': [1.08520] * 60,
                    'Volume': [1000] * 60,
                }, index=dates)
                
                # Calculate indicators
                df_test = calculate_indicators(df_test)
                
                # Force the last row to pass all filters:
                # MACD Crossover:
                df_test.loc[df_test.index[-2], 'MACD'] = 0.00010
                df_test.loc[df_test.index[-2], 'MACD_Signal'] = 0.00015
                df_test.loc[df_test.index[-1], 'MACD'] = 0.00020
                df_test.loc[df_test.index[-1], 'MACD_Signal'] = 0.00018
                
                # Bollinger Band touch:
                df_test.loc[df_test.index[-1], 'BB_Lower'] = 1.08450
                df_test.loc[df_test.index[-1], 'Low'] = 1.08400  # Low <= BB_Lower (Touch!)
                
                # Volume Spike:
                df_test.loc[df_test.index[-2], 'Volume'] = 1000
                df_test.loc[df_test.index[-1], 'Volume'] = 1500  # Spike!
                
                # EMA trend:
                df_test.loc[df_test.index[-1], 'EMA_50'] = 1.08300
                df_test.loc[df_test.index[-1], 'EMA_200'] = 1.08200
                df_test.loc[df_test.index[-1], 'Close'] = 1.08500  # Close > EMA_50 > EMA_200 (True!)
                df_test.loc[df_test.index[-1], 'EMA_200_Slope'] = 0.00001  # Positive slope
                
                # RSI Room to grow & Range:
                df_test.loc[df_test.index[-1], 'RSI_14'] = 43.0  # Between 40 and 55, and < 45 (True!)
                
                # ATR Spike filter:
                df_test.loc[df_test.index[-1], 'ATR_Spike'] = False
                
                # Swing Low Proximity:
                df_test.loc[df_test.index[-1], 'Swing_Low_20'] = 1.08410
                
                # Run check_signals
                df_res = check_signals(df_test, "EURUSD=X")
                
                last_row = df_res.iloc[-1]
                score = last_row['Call_Score']
                
                # Inspect conditions to display in UI
                macd_ok = (df_res['MACD'].iloc[-2] <= df_res['MACD_Signal'].iloc[-2]) and (df_res['MACD'].iloc[-1] > df_res['MACD_Signal'].iloc[-1])
                bb_ok = (df_res['Low'].iloc[-1] <= df_res['BB_Lower'].iloc[-1])
                vol_ok = (df_res['Volume'].iloc[-1] > df_res['Volume'].iloc[-2])
                
                st.markdown(f"**Mock State Verification:** MACD_Cross={macd_ok}, BB_Touch={bb_ok}, Volume_Spike={vol_ok}, Score={score}/5")
                if score == 5:
                    st.success("🟢 **MACD:True BB:True VOL:True EMA:True Score:5/5 -> SIGNAL: CALL**")
                    trigger_confetti()
                else:
                    st.error(f"🔴 **RESULT: BLOCKED (Score was {score}/5)**")
            except Exception as ex:
                st.error(f"Error during self-test: {ex}")
                
        # 4. Alert Test Buttons
        st.markdown("### 🔔 ALERT TEST BUTTONS")
        a1, a2, a3 = st.columns(3)
        with a1:
            if st.button("Send Test Pre-Alert", use_container_width=True):
                pre_msg = f"🚨 <b>PRE-ALERT LOADING... (TEST)</b>\n\n" \
                          f"<b>Pair:</b> EURUSD\n" \
                          f"<b>Direction:</b> 🟢 CALL\n" \
                          f"<b>Session:</b> 🟢 IN-SESSION\n" \
                          f"<b>Time:</b> {datetime.datetime.now(pytz.timezone('Asia/Riyadh')).strftime('%I:%M:%S %p AST')}\n" \
                          f"<b>Status:</b> Waiting for final 20s confirmation...\n" \
                          f"<b>Note:</b> Diagnostics connection check."
                local_send_telegram_alert(pre_msg)
                st.success("Pre-Alert sent!")
        with a2:
            if st.button("Send Test Final Signal", use_container_width=True):
                sig_msg = f"✅ <b>FINAL SIGNAL (TEST)</b>\n\n" \
                          f"<b>Pair:</b> EURUSD\n" \
                          f"<b>Direction:</b> 🟢 CALL\n" \
                          f"<b>Session:</b> 🟢 IN-SESSION\n" \
                          f"<b>Entry Time:</b> {datetime.datetime.now(pytz.timezone('Asia/Riyadh')).strftime('%I:%M %p AST')}\n" \
                          f"<b>Expiry:</b> 15 Minutes\n" \
                          f"<b>Reason:</b> All 5 Confirmations + V4.2 Filters Passed\n" \
                          f"<b>Risk:</b> Low"
                local_send_telegram_alert(sig_msg)
                st.success("Final Signal sent!")
        with a3:
            if st.button("Send Test Hourly Report", use_container_width=True):
                local_send_hourly_summary()
                st.success("Hourly Report sent!")
                
        # 5. Dashboard Health (DB Count & Last 5 Signals Table)
        st.markdown("### 📋 TODAY'S SIGNALS & HEALTH")
        today_sigs_count = 0
        last_5_sigs = []
        
        # Calculate today Riyadh AST start time
        tz_ry = pytz.timezone("Asia/Riyadh")
        now_ry = datetime.datetime.now(tz_ry)
        start_of_day_ry = tz_ry.localize(datetime.datetime(now_ry.year, now_ry.month, now_ry.day, 0, 0, 0))
        start_of_day_utc = start_of_day_ry.astimezone(pytz.utc).isoformat()
        
        if supabase_client is not None:
            try:
                # Query signals from today (Jeddah Time)
                res_all = supabase_client.table("signals").select("*").gte("time", start_of_day_utc).order("time", desc=True).execute()
                all_today_sigs = res_all.data if res_all.data else []
                # Filter strictly 15M
                today_sigs_count = sum(1 for s in all_today_sigs if s["timeframe"].upper() == "15M")
                
                # Fetch last 5 signals regardless of date
                res_5 = supabase_client.table("signals").select("*").order("time", desc=True).limit(5).execute()
                last_5_sigs = res_5.data if res_5.data else []
            except Exception as health_e:
                st.error(f"Error fetching health stats: {health_e}")
                
        st.metric("15M Signals Today", today_sigs_count)
        
        st.markdown("**Last 5 Signals Table**")
        if last_5_sigs:
            rows_list = []
            for s in last_5_sigs:
                sig_time_utc = pd.to_datetime(s["time"])
                sig_time_ry = sig_time_utc.astimezone(pytz.timezone("Asia/Riyadh"))
                time_str = sig_time_ry.strftime("%I:%M %p")
                
                # Determine reason based on score
                confirmations = s.get("confirmations", "0/5")
                if "5/5" in confirmations or s.get("status") == "WIN":
                    reason = f"Fired because: MACD_Cross=True, BB_{'Lower' if s['type']=='CALL' else 'Upper'}=True, Volume_Spike=True, Score=5"
                else:
                    diagnostics_raw = s.get("diagnostics", "")
                    reason = diagnostics_raw if diagnostics_raw else "Score or filters failed."
                    
                rows_list.append({
                    "Time (AST)": time_str,
                    "Pair": s["pair"].replace("=X", ""),
                    "Direction": s["type"],
                    "Score": confirmations,
                    "Result": s["status"],
                    "Reason": reason
                })
            st.table(pd.DataFrame(rows_list))
        else:
            st.info("No signals found in database history.")
            
        # 6. Signal Post-Mortem Table
        st.markdown("### 🔍 SIGNAL POST-MORTEM ANALYZER")
        postmortem_list = []
        if supabase_client is not None:
            try:
                # Fetch resolved signals
                res_all_resolved = supabase_client.table("signals").select("*").order("time", desc=True).limit(20).execute()
                resolved_sigs = res_all_resolved.data if res_all_resolved.data else []
                for s in resolved_sigs:
                    status = s["status"]
                    if status == "PENDING":
                        continue
                    entry = float(s["entry_price"])
                    exit_p = float(s["exit_price"]) if s.get("exit_price") is not None else None
                    pair_name = s["pair"].replace("=X", "")
                    sig_type = s["type"]
                    
                    label = "TP" if status == "WIN" else ("SL" if status == "LOSS" else "TIE")
                    
                    if status == "WIN":
                        if sig_type == "CALL":
                            reason = f"Succeeded: Exit price {exit_p:.5f} was higher than Entry price {entry:.5f}."
                        else:
                            reason = f"Succeeded: Exit price {exit_p:.5f} was lower than Entry price {entry:.5f}."
                    elif status == "LOSS":
                        if sig_type == "CALL":
                            if exit_p is not None:
                                reason = f"Failed: Price did not hold. Reversed to exit price {exit_p:.5f} (lower than Entry {entry:.5f})."
                            else:
                                reason = "Failed: Exit price unavailable."
                        else:
                            if exit_p is not None:
                                reason = f"Failed: Price did not hold. Reversed to exit price {exit_p:.5f} (higher than Entry {entry:.5f})."
                            else:
                                reason = "Failed: Exit price unavailable."
                    else:
                        reason = f"TIE: Exit price {exit_p:.5f} equal to Entry price {entry:.5f}."
                        
                    sig_time_utc = pd.to_datetime(s["time"])
                    sig_time_ry = sig_time_utc.astimezone(pytz.timezone("Asia/Riyadh"))
                    time_str = sig_time_ry.strftime("%Y-%m-%d %I:%M %p")
                    
                    postmortem_list.append({
                        "Time": time_str,
                        "Pair": pair_name,
                        "Type": sig_type,
                        "Entry": entry,
                        "Result": label,
                        "Confirmations": s.get("confirmations", "5/5"),
                        "Diagnostics": reason
                    })
            except Exception as pm_e:
                st.error(f"Error loading post-mortem: {pm_e}")
                
        if postmortem_list:
            html_pm = """
            <table class="vip-table">
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Pair</th>
                        <th>Type</th>
                        <th>Entry</th>
                        <th>Result</th>
                        <th>Confirmations</th>
                        <th>Diagnostics</th>
                    </tr>
                </thead>
                <tbody>
            """
            for row in postmortem_list:
                tr_class = "tr-win" if row["Result"] == "TP" else ("tr-loss" if row["Result"] == "SL" else "")
                badge_class = "vip-badge-win" if row["Result"] == "TP" else ("vip-badge-loss" if row["Result"] == "SL" else "vip-badge-pending")
                
                type_color = "#00ff88" if row["Type"] == "CALL" else "#ff073a"
                
                html_pm += f"""
                <tr class="{tr_class}">
                    <td>{row['Time']}</td>
                    <td style="font-weight:700;">{row['Pair']}</td>
                    <td style="color:{type_color}; font-weight:700;">{row['Type']}</td>
                    <td style="font-family:monospace;">{row['Entry']:.5f}</td>
                    <td><span class="vip-badge {badge_class}">{row['Result']}</span></td>
                    <td style="font-weight:600;">{row['Confirmations']}</td>
                    <td style="font-size:0.8rem; color:#94a3b8;">{row['Diagnostics']}</td>
                </tr>
                """
            html_pm += "</tbody></table>"
            st.markdown(html_pm, unsafe_allow_html=True)
        else:
            st.info("No resolved signals in database to analyze.")

# RIGHT COLUMN - LIVE COMPACT SIGNAL LOGS & METRICS
with col_right:
    st.markdown("## 📡 LOGS & STATS")
    
    if st.session_state.daily_losses >= 3:
        st.error("🚨 STOP TRADING TODAY! DAILY MAX 3 LOSS REACHED.")
        st.session_state.scanning = False
        
    tab_active, tab_overall, tab_postmortem = st.tabs(["🎯 ACTIVE PAIR", "📊 OVERALL ANALYTICS", "🔍 POST-MORTEM"])
    
    with tab_active:
        st.caption(f"Signal Audit: {active_pair.replace('=X','')} [{timeframe}]")
        filtered_log = [sig for sig in st.session_state.signal_history if sig["pair"] == active_pair]
        
        # Wrap logs feed inside a premium vertical scrolling ticker container
        with st.container(height=450):
            if filtered_log:
                ticker_items_html = ""
                # Get the latest 5 signals for the scrolling ticker
                for sig in reversed(filtered_log[-5:]):
                    pair_clean = sig["pair"].replace("=X", "").replace("-USD", "/USD")
                    badge_type = f"<span style='color:#00ff88; font-weight:bold;'>🟢 CALL</span>" if sig["type"] == "CALL" else f"<span style='color:#ff073a; font-weight:bold;'>🔴 PUT</span>"
                    
                    badge_status = ""
                    if sig["status"] == "WIN":
                        badge_status = "<span class='vip-badge vip-badge-win'>WIN</span>"
                    elif sig["status"] == "LOSS":
                        badge_status = "<span class='vip-badge vip-badge-loss'>LOSS</span>"
                    elif sig["status"] == "TIE":
                        badge_status = "<span class='vip-badge' style='background:rgba(255,255,255,0.05); color:#cfd8dc;'>TIE</span>"
                    else:
                        badge_status = "<span class='vip-badge vip-badge-pending'>PENDING</span>"
                        
                    time_str = sig["time"].astimezone(pytz.timezone("Asia/Riyadh")).strftime("%I:%M %p")
                    
                    ticker_items_html += f"""
                    <div class="vip-card" style="margin-bottom:0 !important; padding: 12px !important; display:flex; justify-content:space-between; align-items:center; background:rgba(20, 20, 45, 0.4); border-color:rgba(255, 215, 0, 0.05);">
                        <div>
                            <div style="font-weight:700; font-size:0.9rem; color:#ffffff;">{pair_clean}</div>
                            <div style="font-size:0.75rem; color:#94a3b8;">{time_str} ({sig['confirmations']}/5)</div>
                        </div>
                        <div style="text-align:right;">
                            <div>{badge_type}</div>
                            <div style="margin-top:4px;">{badge_status}</div>
                        </div>
                    </div>
                    """
                
                # Render the infinite ticker loop
                full_ticker_html = f"""
                <div class="ticker-container">
                    <div class="ticker-track">
                        {ticker_items_html}
                        {ticker_items_html}
                    </div>
                </div>
                """
                st.markdown(full_ticker_html, unsafe_allow_html=True)
                
                # CSV Export Button
                try:
                    log_df = pd.DataFrame(filtered_log)
                    # Format times for Excel/CSV readability
                    if 'time' in log_df.columns:
                        log_df['time'] = log_df['time'].apply(lambda x: x.strftime("%Y-%m-%d %I:%M %p") if hasattr(x, 'strftime') else str(x))
                    if 'exit_time' in log_df.columns:
                        log_df['exit_time'] = log_df['exit_time'].apply(lambda x: x.strftime("%Y-%m-%d %I:%M %p") if hasattr(x, 'strftime') else str(x))
                    
                    csv_data = log_df.to_csv(index=False).encode('utf-8')
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.download_button(
                        label="📥 Export Session Log (CSV)",
                        data=csv_data,
                        file_name=f"{active_pair}_signal_history.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                except Exception:
                    pass
            else:
                st.write("No signals triggered on active pair yet.")
                
    with tab_overall:
        st.caption("🏆 SYSTEM PERFORMANCE ANALYTICS")
        
        # Load up to 500 signals to provide adequate history for filters
        all_signals = fetch_all_signals_from_db(limit=500)
        
        if not all_signals:
            st.write("No signals recorded in the database yet.")
        else:
            # Create interactive sub-tabs
            sub_tab_daily, sub_tab_hourly, sub_tab_pairs = st.tabs([
                "📆 DAILY ACCURACY", 
                "🕒 HOURLY COMPARISON", 
                "💱 ACCURACY BY PAIR"
            ])
            
            with sub_tab_daily:
                # Group by calendar date in Riyadh/Jeddah timezone
                import collections
                daily_stats = collections.defaultdict(lambda: {"wins": 0, "losses": 0, "ties": 0, "total": 0})
                tz_ry = pytz.timezone("Asia/Riyadh")
                
                for sig in all_signals:
                    sig_time = pd.to_datetime(sig["time"])
                    if sig_time.tzinfo is None:
                        sig_time = pytz.utc.localize(sig_time)
                    sig_time_ry = sig_time.astimezone(tz_ry)
                    date_str = sig_time_ry.strftime("%Y-%m-%d")
                    
                    status = sig["status"]
                    daily_stats[date_str]["total"] += 1
                    if status == "WIN":
                        daily_stats[date_str]["wins"] += 1
                    elif status == "LOSS":
                        daily_stats[date_str]["losses"] += 1
                    elif status == "TIE":
                        daily_stats[date_str]["ties"] += 1
                
                # Sort dates descending
                sorted_dates = sorted(daily_stats.keys(), reverse=True)
                
                # Render in a clean table
                html_daily = """
                <table style="width:100%; border-collapse: collapse; text-align: left; background-color: #111827; color:#e5e7eb; border-radius: 8px; overflow: hidden; font-size:0.8rem; margin-top: 10px;">
                    <thead>
                        <tr style="background-color: #1f2937; border-bottom: 2px solid #374151;">
                            <th style="padding: 8px 10px;">Date</th>
                            <th style="padding: 8px 10px;">Signals</th>
                            <th style="padding: 8px 10px;">Wins - Losses</th>
                            <th style="padding: 8px 10px;">Accuracy</th>
                        </tr>
                    </thead>
                    <tbody>
                """
                for d in sorted_dates[:7]: # Show last 7 active days
                    w = daily_stats[d]["wins"]
                    l = daily_stats[d]["losses"] + daily_stats[d]["ties"]
                    tot_wl = w + l
                    acc = (w / tot_wl) * 100 if tot_wl > 0 else 0.0
                    acc_color = "#4caf50" if acc >= 60 else ("#ff9800" if acc >= 50 else "#f44336")
                    
                    html_daily += f"""<tr style="border-bottom: 1px solid #374151;">
<td style="padding: 8px 10px; font-weight: 600;">{d}</td>
<td style="padding: 8px 10px;">{daily_stats[d]["total"]}</td>
<td style="padding: 8px 10px; color:#a5d6a7;">{w}W <span style="color:#ef9a9a;">{l}L</span></td>
<td style="padding: 8px 10px; font-weight:bold; color:{acc_color};">{acc:.1f}%</td>
</tr>"""
                html_daily += "</tbody></table>"
                st.markdown(html_daily, unsafe_allow_html=True)
                st.caption("Showing performance statistics for the last 7 active trading days.")

            with sub_tab_hourly:
                # Group by recent hours (1h, 4h, 12h, 24h)
                import datetime
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                
                intervals = {
                    "Last 1 Hour": datetime.timedelta(hours=1),
                    "Last 4 Hours": datetime.timedelta(hours=4),
                    "Last 12 Hours": datetime.timedelta(hours=12),
                    "Last 24 Hours": datetime.timedelta(hours=24)
                }
                
                st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
                col_h1, col_h2 = st.columns(2)
                col_h3, col_h4 = st.columns(2)
                cols = [col_h1, col_h2, col_h3, col_h4]
                
                for idx, (label, delta) in enumerate(intervals.items()):
                    cutoff = now_utc - delta
                    tf_sigs = []
                    for sig in all_signals:
                        sig_time = pd.to_datetime(sig["time"])
                        if sig_time.tzinfo is None:
                            sig_time = pytz.utc.localize(sig_time)
                        if sig_time >= cutoff:
                            tf_sigs.append(sig)
                    
                    w = sum(1 for s in tf_sigs if s["status"] == "WIN")
                    l = sum(1 for s in tf_sigs if s["status"] in ["LOSS", "TIE"])
                    tot_wl = w + l
                    acc = (w / tot_wl) * 100 if tot_wl > 0 else 0.0
                    
                    with cols[idx]:
                        st.metric(
                            label=label,
                            value=f"{acc:.1f}%" if tot_wl > 0 else "0.0%",
                            delta=f"{w}W - {l}L ({len(tf_sigs)} Tot)",
                            delta_color="normal" if acc >= 60 else "inverse"
                        )
                st.caption("Live rolling accuracy filters over the most recent execution windows.")

            with sub_tab_pairs:
                # Group by asset/pair
                pair_stats = collections.defaultdict(lambda: {"wins": 0, "losses": 0, "ties": 0, "total": 0})
                for sig in all_signals:
                    pair = sig["pair"]
                    status = sig["status"]
                    pair_stats[pair]["total"] += 1
                    if status == "WIN":
                        pair_stats[pair]["wins"] += 1
                    elif status == "LOSS":
                        pair_stats[pair]["losses"] += 1
                    elif status == "TIE":
                        pair_stats[pair]["ties"] += 1
                
                # Sort pairs by accuracy
                sorted_pairs = []
                for p, s in pair_stats.items():
                    w = s["wins"]
                    l = s["losses"] + s["ties"]
                    tot_wl = w + l
                    acc = (w / tot_wl) * 100 if tot_wl > 0 else 0.0
                    sorted_pairs.append((p, s["total"], w, l, acc))
                sorted_pairs.sort(key=lambda x: x[4], reverse=True)
                
                html_pairs = """
                <table style="width:100%; border-collapse: collapse; text-align: left; background-color: #111827; color:#e5e7eb; border-radius: 8px; overflow: hidden; font-size:0.8rem; margin-top: 10px;">
                    <thead>
                        <tr style="background-color: #1f2937; border-bottom: 2px solid #374151;">
                            <th style="padding: 8px 10px;">Asset/Pair</th>
                            <th style="padding: 8px 10px;">Trades</th>
                            <th style="padding: 8px 10px;">Wins - Losses</th>
                            <th style="padding: 8px 10px;">Win Rate</th>
                        </tr>
                    </thead>
                    <tbody>
                """
                for p, tot, w, l, acc in sorted_pairs:
                    p_clean = p.replace("=X", "").replace("-USD", "/USD")
                    acc_color = "#4caf50" if acc >= 60 else ("#ff9800" if acc >= 50 else "#f44336")
                    
                    html_pairs += f"""<tr style="border-bottom: 1px solid #374151;">
<td style="padding: 8px 10px; font-weight: 600;">{p_clean}</td>
<td style="padding: 8px 10px;">{tot}</td>
<td style="padding: 8px 10px; color:#a5d6a7;">{w}W <span style="color:#ef9a9a;">{l}L</span></td>
<td style="padding: 8px 10px; font-weight:bold; color:{acc_color};">{acc:.1f}%</td>
</tr>"""
                html_pairs += "</tbody></table>"
                st.markdown(html_pairs, unsafe_allow_html=True)
                st.caption("Sorted by historical accuracy (highest win rate first). Use to spot the most profitable pairs.")

    with tab_postmortem:
        st.caption("🔍 Loss Trades Feature Diagnostics (Post-Mortem Analyzer)")
        
        # Filter for completed LOSS signals
        loss_signals = [s for s in all_signals if s["status"] == "LOSS"] if all_signals else []
        
        if not loss_signals:
            st.success("🎉 No loss trades recorded in the database history!")
        else:
            st.warning(f"Found {len(loss_signals)} loss trades. Click any expander to inspect the market indicator states at trigger time.")
            
            # Render in a scrollable list
            with st.container(height=450):
                for idx, sig in enumerate(loss_signals):
                    sig_time = pd.to_datetime(sig["time"])
                    if sig_time.tzinfo is None:
                        sig_time = pytz.utc.localize(sig_time)
                    sig_time_ry = sig_time.astimezone(pytz.timezone("Asia/Riyadh"))
                    time_str = sig_time_ry.strftime("%Y-%m-%d %I:%M %p")
                    pair_clean = sig["pair"].replace("=X", "").replace("-USD", "/USD")
                    
                    label = f"🔴 {time_str} | {pair_clean} | {sig['type']} ({sig['confirmations']})"
                    
                    with st.expander(label, expanded=False):
                        st.markdown(f"**Trade ID:** `{sig['id']}`")
                        st.markdown(f"**Entry Price:** `{sig['entry_price']:.5f}`  |  **Exit Price:** `{sig['exit_price']:.5f}`")
                        st.markdown("---")
                        st.markdown("**🔬 INDICATOR STATES AT TRIGGER:**")
                        
                        diagnostics_raw = sig.get("diagnostics")
                        if diagnostics_raw and " | " in diagnostics_raw:
                            parts = diagnostics_raw.split(" | ")
                            for p in parts:
                                if ":" in p:
                                    k, v = p.split(":", 1)
                                    st.markdown(f"• **{k.strip()}:** `{v.strip()}`")
                                else:
                                    st.markdown(f"• {p.strip()}")
                        else:
                            st.info("No detailed diagnostics saved for this older signal. Diagnostics logging is only active for new signals generated after this update.")

# Autorefresh script (30 seconds) using native sleep and rerun to prevent browser reload session loss
if supabase_client is not None and "supabase_user" in st.session_state and st.session_state.scanning:
    import time
    time.sleep(30)
    st.rerun()
