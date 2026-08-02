import time
import os
import datetime
import pytz
import secrets
import hashlib
import base64
import requests
import json
import pandas as pd
import numpy as np
import yfinance as yf
from dotenv import load_dotenv
from supabase import create_client, Client, ClientOptions
import asyncio
import websockets
import settings_manager

# Load env using absolute path of current folder
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, ".env")
load_dotenv(dotenv_path=env_path)

def clean_env_var(val):
    if val:
        return val.strip().strip('"').strip("'")
    return val

SUPABASE_URL = clean_env_var(os.environ.get("SUPABASE_URL"))
SUPABASE_KEY = clean_env_var(os.environ.get("SUPABASE_KEY"))
TELEGRAM_BOT_TOKEN = clean_env_var(os.environ.get("TELEGRAM_BOT_TOKEN"))
TELEGRAM_CHAT_ID = clean_env_var(os.environ.get("TELEGRAM_CHAT_ID"))

# Tickers & Pairs list - Matches app.py
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

# Scaled volatility thresholds lookup - Matches app.py
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

# Scan settings
TIMEFRAMES = ["5m", "15m"]

# Debug Mode tracking variables
LAST_DEBUG_REPORT_TIME = None
LAST_HOURLY_SENT_HOUR = None
LAST_DAILY_SENT_DATE = None
LAST_DIAGNOSTICS_SENT_TIME = None
LAST_SCAN_SCORES = {}

def get_supabase_client():
    if not SUPABASE_URL or "your-project-id" in SUPABASE_URL:
        print("Error: Supabase Credentials not configured in .env")
        return None
    try:
        # Standard server-side client config
        options = ClientOptions(auto_refresh_token=False, persist_session=False)
        return create_client(SUPABASE_URL, SUPABASE_KEY, options=options)
    except Exception as e:
        print(f"Failed to create Supabase client: {e}")
        return None

supabase_client = get_supabase_client()

def get_active_sessions_string():
    import datetime
    import pytz
    ast = pytz.timezone('Asia/Riyadh')
    now_ast = datetime.datetime.now(ast)
    current_time = now_ast.time()
    
    active = []
    # Sydney: 01:00 to 10:00 AST
    if datetime.time(1, 0) <= current_time <= datetime.time(10, 0):
        active.append("🇦🇺 Sydney")
    # Tokyo: 03:00 to 12:00 AST
    if datetime.time(3, 0) <= current_time <= datetime.time(12, 0):
        active.append("🇯🇵 Tokyo")
    # London: 10:00 to 19:00 AST
    if datetime.time(10, 0) <= current_time <= datetime.time(19, 0):
        active.append("🇬🇧 London")
    # New York: 15:00 to 24:00 (12:00 AM) AST
    if current_time >= datetime.time(15, 0) or current_time < datetime.time(0, 0):
        if datetime.time(15, 0) <= current_time <= datetime.time(23, 59, 59):
            active.append("🇺🇸 New York")
            
    if not active:
        return "😴 Market Quiet (No Main Sessions)"
    return ", ".join(active)

# ----------------- TELEGRAM NOTIFICATIONS -----------------
def send_telegram_alert(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
        
    # Automatically split messages exceeding Telegram's 4096 character limit
    if len(text) > 4000:
        lines = text.split("\n")
        current_chunk = ""
        for line in lines:
            if len(current_chunk) + len(line) + 1 > 4000:
                send_telegram_alert(current_chunk)
                current_chunk = line
            else:
                current_chunk += ("\n" if current_chunk else "") + line
        if current_chunk:
            send_telegram_alert(current_chunk)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")

def send_daily_summary():
    if supabase_client is None:
        return
    try:
        import datetime
        import pytz
        import pandas as pd
        
        tz_ry = pytz.timezone("Asia/Riyadh")
        now_ry = datetime.datetime.now(tz_ry)
        start_of_day_ry = tz_ry.localize(datetime.datetime(now_ry.year, now_ry.month, now_ry.day, 0, 0, 0))
        start_of_day_utc = start_of_day_ry.astimezone(pytz.utc).isoformat()
        
        res = supabase_client.table("signals").select("*").gte("time", start_of_day_utc).order("time", desc=True).execute()
        signals = res.data if res.data else []
        
        date_str = now_ry.strftime("%d/%m/%Y")
        
        # Retroactively classify signals session types if missing
        for s in signals:
            if not s.get("session_type"):
                sig_time = pd.to_datetime(s["time"])
                s["session_type"] = get_session_type(sig_time)
                
        in_sess_sigs = [s for s in signals if s.get("session_type") == "IN-SESSION"]
        off_sess_sigs = [s for s in signals if s.get("session_type") == "OFF-SESSION"]
        
        # Calculate In-Session Stats
        in_wins = sum(1 for s in in_sess_sigs if s["status"] == "WIN")
        in_losses = sum(1 for s in in_sess_sigs if s["status"] in ["LOSS", "TIE"])
        in_total = len(in_sess_sigs)
        in_total_wl = in_wins + in_losses
        in_winrate = (in_wins / in_total_wl) * 100 if in_total_wl > 0 else 0.0
        in_profit = in_wins * 8.00 + in_losses * -10.00
        
        # Calculate Off-Session Stats
        off_wins = sum(1 for s in off_sess_sigs if s["status"] == "WIN")
        off_losses = sum(1 for s in off_sess_sigs if s["status"] in ["LOSS", "TIE"])
        off_total = len(off_sess_sigs)
        off_total_wl = off_wins + off_losses
        off_winrate = (off_wins / off_total_wl) * 100 if off_total_wl > 0 else 0.0
        off_profit = off_wins * 8.00 + off_losses * -10.00
        
        # Calculate Overall Stats
        overall_total = len(signals)
        overall_wins = in_wins + off_wins
        overall_losses = in_losses + off_losses
        overall_wl = overall_wins + overall_losses
        overall_winrate = (overall_wins / overall_wl) * 100 if overall_wl > 0 else 0.0
        
        overall_profit = in_profit + off_profit
        
        # Build Report Message
        msg = f"📊 <b>DAILY PERFORMANCE REPORT - {date_str}</b>\n\n"
        
        msg += f"<b>--- 🟢 IN-SESSION RESULTS ---</b>\n"
        msg += f"Time: 10AM-10PM AST | Signals: {in_total} | Wins: {in_wins} | Losses: {in_losses} | Winrate: {in_winrate:.1f}% | Profit: ${in_profit:+.2f}\n\n"
        
        msg += f"<b>--- 🟡 OFF-SESSION RESULTS ---</b>\n"
        msg += f"Time: 10PM-10AM AST | Signals: {off_total} | Wins: {off_wins} | Losses: {off_losses} | Winrate: {off_winrate:.1f}% | Profit: ${off_profit:+.2f}\n\n"
        
        msg += f"<b>--- OVERALL TOTAL ---</b>\n"
        msg += f"Total Signals: {overall_total} | Overall Winrate: {overall_winrate:.1f}% | Net Profit: ${overall_profit:+.2f}\n\n"
        
        # Append today's trades list
        msg += f"<b>--- 📋 TODAY'S SIGNALS LIST ---</b>\n"
        if signals:
            msg += "<b>🟢 IN-SESSION:</b>\n"
            if in_sess_sigs:
                for sig in in_sess_sigs:
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
                    
                    conf_val = sig.get("confirmations", "N/A")
                    strength_val = sig.get("strength", "NORMAL")
                    tf_val = sig.get("timeframe", "15M").upper()
                    expiry_val = "5m Exp" if tf_val == "5M" else "15m Exp"
                    msg += f"• <code>{time_str}</code> | <b>{pair_clean}</b> | {status_emoji} | <i>{conf_val} ({strength_val} - {expiry_val})</i>\n"
            else:
                msg += "<i>No in-session trades triggered.</i>\n"
                
            msg += "\n<b>🟡 OFF-SESSION:</b>\n"
            if off_sess_sigs:
                for sig in off_sess_sigs:
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
                    
                    conf_val = sig.get("confirmations", "N/A")
                    strength_val = sig.get("strength", "NORMAL")
                    tf_val = sig.get("timeframe", "15M").upper()
                    expiry_val = "5m Exp" if tf_val == "5M" else "15m Exp"
                    msg += f"• <code>{time_str}</code> | <b>{pair_clean}</b> | {status_emoji} | <i>{conf_val} ({strength_val} - {expiry_val})</i>\n"
            else:
                msg += "<i>No off-session trades triggered.</i>\n"
        else:
            msg += "<i>No trades triggered today.</i>\n"
            
        send_telegram_alert(msg)
        print(f"[SUMMARY] Daily summary successfully sent at 9:00 PM AST.")
    except Exception as e:
        print(f"Error generating daily summary: {e}")

# ----------------- TECHNICAL INDICATORS -----------------
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

# ----------------- DB OPERATIONS -----------------
def fetch_pending_signals():
    if supabase_client is None:
        return []
    try:
        res = supabase_client.table("signals").select("*").eq("status", "PENDING").execute()
        return res.data if res.data else []
    except Exception as e:
        print(f"Failed to fetch pending signals: {e}")
        return []

def generate_diagnostics_string(closed_candle, pair, timeframe, sig_type):
    try:
        rsi = float(closed_candle.get('RSI_14', 0))
        close = float(closed_candle.get('Close', 0))
        ema200 = float(closed_candle.get('EMA_200', 0))
        ema50 = float(closed_candle.get('EMA_50', 0))
        macd = float(closed_candle.get('MACD', 0))
        macd_sig = float(closed_candle.get('MACD_Signal', 0))
        bb_upper = float(closed_candle.get('BB_Upper', 0))
        bb_lower = float(closed_candle.get('BB_Lower', 0))
        atr = float(closed_candle.get('ATR', 0))
        
        bb_dist = close - bb_lower if sig_type == "CALL" else bb_upper - close
        ema_dist = close - ema200
        
        mtf_status = "N/A"
        if timeframe == "5m":
            mtf_status = "BULLISH" if check_mtf_trend_ok(pair, "CALL") else ("BEARISH" if check_mtf_trend_ok(pair, "PUT") else "CONSOLIDATING")
            
        diag = (
            f"Type: {sig_type} | Timeframe: {timeframe} | Close: {close:.5f} | "
            f"RSI: {rsi:.1f} | EMA200: {ema200:.5f} (Dist: {ema_dist:.5f}) | "
            f"EMA50: {ema50:.5f} | MACD: {macd:.5f}/Sig: {macd_sig:.5f} | "
            f"BB Upper: {bb_upper:.5f}/BB Lower: {bb_lower:.5f} (Trigger Dist: {bb_dist:.5f}) | "
            f"ATR: {atr:.5f} | 15m MTF Trend: {mtf_status}"
        )
        return diag
    except Exception as e:
        return f"Error generating diagnostics: {e}"

def get_session_type(time_val):
    """
    Checks if time_val (tz-aware or naive) is within 10:00 AM AST to 10:00 PM AST (Jeddah Time).
    (10:00 to 22:00 in AST). Returns 'IN-SESSION' or 'OFF-SESSION'.
    """
    import pytz
    ast_tz = pytz.timezone('Asia/Riyadh')
    # If naive, assume it is UTC as per standard DB timestamps
    if time_val.tzinfo is None:
        time_val_ast = pytz.utc.localize(time_val).astimezone(ast_tz)
    else:
        time_val_ast = time_val.astimezone(ast_tz)
    
    current_hour = time_val_ast.hour
    if 10 <= current_hour < 22:
        return "IN-SESSION"
    return "OFF-SESSION"

def save_signal_to_db(sig):
    if supabase_client is None:
        return False
    try:
        # Check for duplicate
        time_str = sig["time"].isoformat() if hasattr(sig["time"], "isoformat") else str(sig["time"])
        duplicate_check = supabase_client.table("signals").select("id").eq("pair", sig["pair"]).eq("timeframe", sig["timeframe"]).eq("time", time_str).execute()
        if duplicate_check.data:
            return False # Skip duplicate

        sig_data = {
            "id": sig["id"],
            "time": time_str,
            "pair": sig["pair"],
            "timeframe": sig["timeframe"],
            "type": sig["type"],
            "entry_price": float(sig["entry_price"]),
            "exit_time": sig["exit_time"].isoformat() if hasattr(sig["exit_time"], "isoformat") else str(sig["exit_time"]),
            "exit_price": float(sig["exit_price"]) if sig["exit_price"] is not None else None,
            "status": sig["status"],
            "strength": sig["strength"],
            "confirmations": sig["confirmations"],
            "patterns": sig["patterns"],
            "diagnostics": sig.get("diagnostics", "N/A"),
            "session_type": sig.get("session_type", "IN-SESSION")
        }
        try:
            supabase_client.table("signals").insert(sig_data).execute()
        except Exception as e:
            # Fallback if diagnostics or session_type columns do not exist in database schema yet
            print(f"[DB Warning] Insertion with new columns failed, retrying fallback: {e}")
            sig_data_fallback = sig_data.copy()
            sig_data_fallback.pop("diagnostics", None)
            sig_data_fallback.pop("session_type", None)
            supabase_client.table("signals").insert(sig_data_fallback).execute()
        return True
    except Exception as e:
        print(f"Failed to save signal to database: {e}")
        return False

def save_trade_log_to_db(sig, closed_candle, session_type, is_strong_plus_plus):
    if supabase_client is None:
        return False
    try:
        # Determine logical status values
        macd_status = "Bullish Cross" if sig["type"] == "CALL" else "Bearish Cross"
        bollinger_status = "Bounce Lower Band" if sig["type"] == "CALL" else "Bounce Upper Band"
        
        # MTF Trend
        mtf_status = "EMA200 UP" if sig["type"] == "CALL" else "EMA200 DOWN"
        
        # Pivot SR
        swing_low = closed_candle.get('Swing_Low_20', 0.0)
        swing_high = closed_candle.get('Swing_High_20', 0.0)
        pivot_sr_status = f"Near Support {swing_low:.5f}" if sig["type"] == "CALL" else f"Near Resistance {swing_high:.5f}"
        
        # Expiry minutes
        expiry_minutes = 15 if is_strong_plus_plus else 5
        
        log_data = {
            "id": sig["id"],
            "timestamp": sig["time"].isoformat() if hasattr(sig["time"], "isoformat") else str(sig["time"]),
            "pair": sig["pair"].replace("=X", ""),
            "direction": sig["type"],
            "session_type": session_type,
            "confirmation_score": sig["confirmations"],
            "macd_status": macd_status,
            "bollinger_status": bollinger_status,
            "rsi_value": float(closed_candle.get('RSI_14', 50.0)),
            "ema200_slope_5m": float(closed_candle.get('EMA_200_Slope', 0.0)),
            "candle_pattern": closed_candle.get('Pattern_Label', "None") or "None",
            "mtf_15m_status": mtf_status,
            "atr_value": float(closed_candle.get('ATR', 0.0)),
            "pivot_sr_status": pivot_sr_status,
            "expiry_minutes": expiry_minutes,
            "result": "PENDING"
        }
        
        supabase_client.table("trade_logs").insert(log_data).execute()
        print(f"[Autopsy] Successfully saved trade log for signal: {sig['id']}")
        return True
    except Exception as e:
        print(f"[Autopsy Warning] Failed to save trade log: {e}")
        return False

def update_trade_log_in_db(sig_id, result):
    if supabase_client is None:
        return False
    try:
        supabase_client.table("trade_logs").update({"result": result}).eq("id", sig_id).execute()
        print(f"[Autopsy] Successfully updated trade log {sig_id} result to {result}")
        return True
    except Exception as e:
        print(f"[Autopsy Warning] Failed to update trade log: {e}")
        return False

def update_signal_in_db(sig_id, exit_price, status):
    if supabase_client is None:
        return
    try:
        payload = {
            "exit_price": float(exit_price) if exit_price is not None else None,
            "status": status
        }
        supabase_client.table("signals").update(payload).eq("id", sig_id).execute()
        print(f"Signal resolved: ID={sig_id}, Exit={exit_price}, Status={status}")
    except Exception as e:
        print(f"Failed to update signal in database: {e}")

# ----------------- SCANNING CORE -----------------
last_processed_candles = {} # Keeps track of (pair, timeframe): last_timestamp

def check_mtf_trend_ok(pair, sig_type):
    """
    Downloads 15m data for the pair and returns True if:
      - For CALL: 15m EMA_50 > EMA_200
      - For PUT: 15m EMA_50 < EMA_200
    Otherwise returns False.
    """
    try:
        df_15m = download_market_data(pair, "15m", period="5d")
        if df_15m.empty or len(df_15m) < 200:
            return False
            
        if isinstance(df_15m.columns, pd.MultiIndex):
            df_15m.columns = df_15m.columns.get_level_values(0)
            
        ema_50 = df_15m['Close'].ewm(span=50, adjust=False).mean()
        ema_200 = df_15m['Close'].ewm(span=200, adjust=False).mean()
        
        last_ema_50 = ema_50.iloc[-2]
        last_ema_200 = ema_200.iloc[-2]
        
        if sig_type == "CALL":
            return last_ema_50 > last_ema_200
        elif sig_type == "PUT":
            return last_ema_50 < last_ema_200
        return False
    except Exception as e:
        print(f"Error checking 15m MTF trend for {pair}: {e}")
        return False

def check_v4_sniper_filters_ok(closed_candle, pair, sig_type):
    # 1. EMA200 Slope Filter
    ema_slope = closed_candle.get('EMA_200_Slope', 0.0)
    if sig_type == "CALL" and ema_slope <= 0:
        return False
    if sig_type == "PUT" and ema_slope >= 0:
        return False
        
    # 2. RSI Zone Strict
    rsi = closed_candle.get('RSI_14', 50.0)
    if sig_type == "CALL" and not (40 <= rsi <= 55):
        return False
    if sig_type == "PUT" and not (45 <= rsi <= 60):
        return False
        
    # 3. ATR Spike Filter
    if closed_candle.get('ATR_Spike', False):
        return False
        
    # 4. Pivot Level Confirmation
    pips_mult = 0.01 if "JPY" in pair else 0.0001
    ten_pips = 10 * pips_mult
    if sig_type == "CALL":
        swing_low = closed_candle.get('Swing_Low_20', 0.0)
        bb_lower = closed_candle.get('BB_Lower', 0.0)
        if abs(bb_lower - swing_low) > ten_pips:
            return False
    elif sig_type == "PUT":
        swing_high = closed_candle.get('Swing_High_20', 0.0)
        bb_upper = closed_candle.get('BB_Upper', 0.0)
        if abs(bb_upper - swing_high) > ten_pips:
            return False
            
    return True

def get_scan_rejection_reason(closed_candle, pair, timeframe):
    """
    Evaluates closed_candle step-by-step to identify the exact technical reason why a potential trade was rejected.
    """
    # Replaced session constraints check to allow off-session signals
    pass

    call_score = int(closed_candle.get('Call_Score', 0))
    put_score = int(closed_candle.get('Put_Score', 0))
    
    # Determine target direction (prefer higher score candidate, fallback to trigger checks)
    sig_type = None
    if call_score > 0 or put_score > 0:
        sig_type = "CALL" if call_score >= put_score else "PUT"
    else:
        # Check if MACD cross or BB triggers occurred but filters wiped them out
        macd = closed_candle.get('MACD', 0.0)
        signal = closed_candle.get('MACD_Signal', 0.0)
        close = closed_candle.get('Close', 0.0)
        open_val = closed_candle.get('Open', 0.0)
        low = closed_candle.get('Low', 0.0)
        high = closed_candle.get('High', 0.0)
        bb_lower = closed_candle.get('BB_Lower', 0.0)
        bb_upper = closed_candle.get('BB_Upper', 0.0)
        
        # Approximate trigger checks
        call_trig = (macd > signal) or (low <= bb_lower and close > open_val)
        put_trig = (macd < signal) or (high >= bb_upper and close < open_val)
        if call_trig:
            sig_type = "CALL"
        elif put_trig:
            sig_type = "PUT"
        else:
            return "SCORE_LOW"

    # Enforce EMA200 slope direction
    ema_slope = float(closed_candle.get('EMA_200_Slope', 0.0))
    if sig_type == "CALL" and ema_slope <= 0:
        return f"EMA200_SLOPE_NEGATIVE_({ema_slope:.7f})"
    elif sig_type == "PUT" and ema_slope >= 0:
        return f"EMA200_SLOPE_POSITIVE_({ema_slope:.7f})"
        
    # Enforce RSI Strict Zones
    rsi_val = float(closed_candle.get('RSI_14', 50.0))
    if sig_type == "CALL" and not (40 <= rsi_val <= 55):
        return f"RSI_OUT_OF_RANGE_({rsi_val:.2f}_not_in_40-55)"
    elif sig_type == "PUT" and not (45 <= rsi_val <= 60):
        return f"RSI_OUT_OF_RANGE_({rsi_val:.2f}_not_in_45-60)"
        
    # Enforce ATR news spike block
    if closed_candle.get('ATR_Spike', False):
        return "ATR_SPIKE_LIMIT_EXCEEDED"
        
    # Enforce Pivot S/R boundaries
    is_jpy = "JPY" in str(pair)
    pips_mult = 0.01 if is_jpy else 0.0001
    ten_pips = 10 * pips_mult
    bb_lower = float(closed_candle.get('BB_Lower', 0.0))
    bb_upper = float(closed_candle.get('BB_Upper', 0.0))
    swing_low = float(closed_candle.get('Swing_Low_20', 0.0))
    swing_high = float(closed_candle.get('Swing_High_20', 0.0))
    
    if sig_type == "CALL":
        dist = abs(bb_lower - swing_low)
        if dist > ten_pips:
            return f"PIVOT_SR_FAILED_(dist:{dist/pips_mult:.1f}pips_limit:10)"
    else:
        dist = abs(bb_upper - swing_high)
        if dist > ten_pips:
            return f"PIVOT_SR_FAILED_(dist:{dist/pips_mult:.1f}pips_limit:10)"
            
    # Enforce MTF Trend Shield (15M check)
    if timeframe == "5m":
        if not check_mtf_trend_ok(pair, sig_type):
            return "MTF_15M_TREND_MISALIGNMENT"
            
    # Enforce Candlestick pattern filters
    pattern = closed_candle.get('Pattern_Label', 'None')
    if pattern and any(bad_pat in pattern for bad_pat in ["Doji", "Shooting Star", "3 Crows"]):
        return f"PATTERN_REVERSED_({pattern})"
        
    # If it passed all filters but score is < 5
    score = call_score if sig_type == "CALL" else put_score
    if score < 5:
        return "SCORE_LOW"
        
    return "NONE"

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
    "CRASH_500": "CRASH500",
    "BOOM_500": "BOOM500",
    "CRASH_1000": "CRASH1000",
    "BOOM_1000": "BOOM1000"
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

def process_market_signals(pair, timeframe):
    lookback = "2d" if timeframe == "5m" else ("5d" if timeframe == "15m" else "1d")
    
    try:
        df = download_market_data(pair, timeframe, period=lookback)
        if df.empty:
            return
            
        df = calculate_indicators(df)
        df = check_signals(df, pair)
        
        if len(df) < 2:
            return

        # Smart Closed Candle selection (bypass yfinance active candle latency)
        import datetime
        import pytz
        now_utc = datetime.datetime.now(pytz.utc)
        delta_t = (datetime.timedelta(minutes=1) if timeframe == "1m" else (datetime.timedelta(minutes=5) if timeframe == "5m" else datetime.timedelta(minutes=15)))
        
        last_candle_time = df.index[-1]
        if last_candle_time.tzinfo is None:
            last_candle_time = pytz.utc.localize(last_candle_time)
        else:
            last_candle_time = last_candle_time.astimezone(pytz.utc)
            
        last_candle_end = last_candle_time + delta_t
        
        if now_utc >= last_candle_end:
            closed_candle = df.iloc[-1]
            closed_candle_time = df.index[-1]
        else:
            closed_candle = df.iloc[-2]
            closed_candle_time = df.index[-2]
        
        # Determine current AST time for logging
        ast_tz = pytz.timezone("Asia/Riyadh")
        ast_now = datetime.datetime.now(ast_tz)
        ast_time_str = ast_now.strftime("%H:%M AST")
        
        session_type = get_session_type(closed_candle_time)
        session_label = "🟢 IN-SESSION" if session_type == "IN-SESSION" else "🟡 OFF-SESSION"
        
        call_score = int(closed_candle.get('Call_Score', 0))
        put_score = int(closed_candle.get('Put_Score', 0))
        max_score = max(call_score, put_score)
        
        # Save max score to global dict for debug heartbeat reporting
        LAST_SCAN_SCORES[pair] = max_score
        
        # Determine rejected reason
        volatility_low = closed_candle.get('Low_Volatility', False)
        if volatility_low:
            reason = "LOW_VOLATILITY"
        else:
            reason = get_scan_rejection_reason(closed_candle, pair, timeframe)
            
        print(f"[SCAN] {pair.replace('=X', '')} {timeframe.upper()} - Time: {ast_time_str} - Session: {session_label} - Score: {max_score}/5 - REASON BLOCKED: {reason}")

        # Prevent double-processing the same candle
        key = (pair, timeframe)
        if last_processed_candles.get(key) == closed_candle_time:
            return
        
        last_processed_candles[key] = closed_candle_time
        
        # Volatility check
        volatility_low = closed_candle['Low_Volatility']
        if volatility_low:
            return # Skip signal checks in low volatility environment
            
        sig_type = None
        confirmations = 0
        
        # Determine score threshold (V4.2 Sniper: Strictly 5/5 confirmations)
        min_score = 5
        
        if closed_candle['Call_Score'] >= min_score:
            sig_type = "CALL"
            confirmations = closed_candle['Call_Score']
        elif closed_candle['Put_Score'] >= min_score:
            sig_type = "PUT"
            confirmations = closed_candle['Put_Score']
            
        if sig_type:
            # Enforce MTF Hard Rule for 5m signals (redundant for 15m, but kept for logic safety)
            if timeframe == "5m" and not check_mtf_trend_ok(pair, sig_type):
                return
                
            # Enforce V4 Sniper Filters
            if not check_v4_sniper_filters_ok(closed_candle, pair, sig_type):
                return
                
            # Expiry selection logic (V4.2 Sniper Update: Strictly 15 Minutes)
            expiry_str = "15 Minutes"
            expiry_delta = delta_t
            exit_time = closed_candle_time + expiry_delta
            
            pattern = closed_candle['Pattern_Label']
            # Skip low-winrate patterns (Doji, Shooting Star, 3 Crows)
            if pattern and any(bad_pat in pattern for bad_pat in ["Doji", "Shooting Star", "3 Crows"]):
                return False
                
            strength = "NORMAL"
            if pattern:
                strength = "STRONG"
                
            # Strict Session Block disabled to allow off-session signals
            pass
                
            is_marubozu = (
                'Pattern_Marubozu' in closed_candle and 
                closed_candle['Pattern_Marubozu'] and 
                (
                    (sig_type == "CALL" and closed_candle['Close'] > closed_candle['Open']) or
                    (sig_type == "PUT" and closed_candle['Close'] < closed_candle['Open'])
                )
            )

            new_sig = {
                "id": str(int(time.time())) + f"-{pair}-{timeframe}",
                "time": closed_candle_time,
                "pair": pair,
                "timeframe": timeframe.upper(), # Save uppercase "15M" to database
                "type": sig_type,
                "entry_price": float(closed_candle['Close']),
                "exit_time": exit_time,
                "exit_price": None,
                "status": "PENDING",
                "strength": strength,
                "confirmations": f"{confirmations}/5",
                "patterns": pattern if pattern else "None",
                "diagnostics": generate_diagnostics_string(closed_candle, pair, timeframe, sig_type),
                "session_type": session_type
            }
            
            success = save_signal_to_db(new_sig)
            if success:
                save_trade_log_to_db(new_sig, closed_candle, session_type, is_marubozu)
                # Convert closed_candle_time to Riyadh AST and UTC
                ast_tz = pytz.timezone("Asia/Riyadh")
                if closed_candle_time.tzinfo is not None:
                    closed_candle_time_ast = closed_candle_time.astimezone(ast_tz)
                else:
                    closed_candle_time_ast = pytz.utc.localize(closed_candle_time).astimezone(ast_tz)
                
                closed_candle_time_utc = closed_candle_time_ast.astimezone(pytz.utc)
                
                # Trade Entry Time is when the signal candle ends
                trade_entry_time_ast = closed_candle_time_ast + delta_t
                trade_entry_time_utc = closed_candle_time_utc + delta_t
                
                trade_entry_ast_str = trade_entry_time_ast.strftime("%I:%M %p AST")
                trade_entry_utc_str = trade_entry_time_utc.strftime("%I:%M %p UTC")
                trade_entry_display = f"{trade_entry_ast_str} ({trade_entry_utc_str})"
                
                print(f"[SIGNAL] NEW Central Signal: {pair} [{timeframe}] {sig_type} at {trade_entry_display}")
                
                # Format and send Telegram notification
                tg_text = f"✅ <b>FINAL SIGNAL</b>\n\n" \
                          f"<b>Pair:</b> {pair.replace('=X', '')}\n" \
                          f"<b>Direction:</b> {'🟢 CALL' if sig_type == 'CALL' else '🔴 PUT'}\n" \
                          f"<b>Session:</b> {session_label}\n" \
                          f"<b>Entry Time:</b> {trade_entry_display}\n" \
                          f"<b>Expiry:</b> {expiry_str}\n" \
                          f"<b>Reason:</b> All {confirmations} Confirmations + V4 Filters Passed\n" \
                          f"<b>Risk:</b> Low"
                send_telegram_alert(tg_text)
                return True
        return False
    except Exception as e:
        print(f"Error processing market signals for {pair} [{timeframe}]: {e}")
        return False

def process_market_signals_prefetched(pair, timeframe, df):
    if df.empty:
        return
    try:
        df = calculate_indicators(df)
        df = check_signals(df, pair)
        
        if len(df) < 2:
            return

        # Smart Closed Candle selection (bypass yfinance active candle latency)
        import datetime
        import pytz
        now_utc = datetime.datetime.now(pytz.utc)
        delta_t = (datetime.timedelta(minutes=1) if timeframe == "1m" else (datetime.timedelta(minutes=5) if timeframe == "5m" else datetime.timedelta(minutes=15)))
        
        last_candle_time = df.index[-1]
        if last_candle_time.tzinfo is None:
            last_candle_time = pytz.utc.localize(last_candle_time)
        else:
            last_candle_time = last_candle_time.astimezone(pytz.utc)
            
        last_candle_end = last_candle_time + delta_t
        
        if now_utc >= last_candle_end:
            closed_candle = df.iloc[-1]
            closed_candle_time = df.index[-1]
        else:
            closed_candle = df.iloc[-2]
            closed_candle_time = df.index[-2]
        
        # Prevent double-processing the same candle
        key = (pair, timeframe)
        if last_processed_candles.get(key) == closed_candle_time:
            return
        
        last_processed_candles[key] = closed_candle_time
        
        # Volatility check
        volatility_low = closed_candle['Low_Volatility']
        if volatility_low:
            return # Skip signal checks in low volatility environment
            
        sig_type = None
        confirmations = 0
        
        # Determine score threshold (V4.2 Sniper: Strictly 5/5 confirmations)
        min_score = 5
        
        if closed_candle['Call_Score'] >= min_score:
            sig_type = "CALL"
            confirmations = closed_candle['Call_Score']
        elif closed_candle['Put_Score'] >= min_score:
            sig_type = "PUT"
            confirmations = closed_candle['Put_Score']
            
        if sig_type:
            # Enforce MTF Hard Rule for 5m signals (redundant for 15m, but kept for logic safety)
            if timeframe == "5m" and not check_mtf_trend_ok(pair, sig_type):
                return
                
            # Enforce V4 Sniper Filters
            if not check_v4_sniper_filters_ok(closed_candle, pair, sig_type):
                return
                
            # Expiry selection logic (V4.2 Sniper Update: Strictly 15 Minutes)
            expiry_str = "15 Minutes"
            expiry_delta = delta_t
            exit_time = closed_candle_time + expiry_delta
            
            pattern = closed_candle['Pattern_Label']
            # Skip low-winrate patterns (Doji, Shooting Star, 3 Crows)
            if pattern and any(bad_pat in pattern for bad_pat in ["Doji", "Shooting Star", "3 Crows"]):
                return False
                
            strength = "NORMAL"
            if pattern:
                strength = "STRONG"
                
            session_type = get_session_type(closed_candle_time)
            # Strict Session Block (V4.2 Sniper)
            if session_type != "IN-SESSION":
                return False
                
            session_label = "🟢 IN-SESSION" if session_type == "IN-SESSION" else "🟡 OFF-SESSION"
            
            is_marubozu = (
                'Pattern_Marubozu' in closed_candle and 
                closed_candle['Pattern_Marubozu'] and 
                (
                    (sig_type == "CALL" and closed_candle['Close'] > closed_candle['Open']) or
                    (sig_type == "PUT" and closed_candle['Close'] < closed_candle['Open'])
                )
            )

            new_sig = {
                "id": str(int(time.time())) + f"-{pair}-{timeframe}",
                "time": closed_candle_time,
                "pair": pair,
                "timeframe": timeframe.upper(), # Save uppercase "15M" to database
                "type": sig_type,
                "entry_price": float(closed_candle['Close']),
                "exit_time": exit_time,
                "exit_price": None,
                "status": "PENDING",
                "strength": strength,
                "confirmations": f"{confirmations}/5",
                "patterns": pattern if pattern else "None",
                "diagnostics": generate_diagnostics_string(closed_candle, pair, timeframe, sig_type),
                "session_type": session_type
            }
            
            success = save_signal_to_db(new_sig)
            if success:
                save_trade_log_to_db(new_sig, closed_candle, session_type, is_marubozu)
                # Convert closed_candle_time to Riyadh AST and UTC
                ast_tz = pytz.timezone("Asia/Riyadh")
                if closed_candle_time.tzinfo is not None:
                    closed_candle_time_ast = closed_candle_time.astimezone(ast_tz)
                else:
                    closed_candle_time_ast = pytz.utc.localize(closed_candle_time).astimezone(ast_tz)
                
                closed_candle_time_utc = closed_candle_time_ast.astimezone(pytz.utc)
                
                # Trade Entry Time is when the signal candle ends
                trade_entry_time_ast = closed_candle_time_ast + delta_t
                trade_entry_time_utc = closed_candle_time_utc + delta_t
                
                trade_entry_ast_str = trade_entry_time_ast.strftime("%I:%M %p AST")
                trade_entry_utc_str = trade_entry_time_utc.strftime("%I:%M %p UTC")
                trade_entry_display = f"{trade_entry_ast_str} ({trade_entry_utc_str})"
                
                print(f"[SIGNAL] NEW Central Signal: {pair} [{timeframe}] {sig_type} at {trade_entry_display}")
                
                # Format and send Telegram notification
                tg_text = f"✅ <b>FINAL SIGNAL</b>\n\n" \
                          f"<b>Pair:</b> {pair.replace('=X', '')}\n" \
                          f"<b>Direction:</b> {'🟢 CALL' if sig_type == 'CALL' else '🔴 PUT'}\n" \
                          f"<b>Session:</b> {session_label}\n" \
                          f"<b>Entry Time:</b> {trade_entry_display}\n" \
                          f"<b>Expiry:</b> {expiry_str}\n" \
                          f"<b>Reason:</b> All {confirmations} Confirmations + V4 Filters Passed\n" \
                          f"<b>Risk:</b> Low"
                send_telegram_alert(tg_text)
                return True
        return False
    except Exception as e:
        print(f"Error prefetched processing for {pair} [{timeframe}]: {e}")
        return False

def send_diagnostics_heartbeat():
    if supabase_client is None:
        return
    try:
        import requests
        import datetime
        import pytz
        
        # 1. DB status
        db_ok = False
        try:
            supabase_client.table("signals").select("*").limit(1).execute()
            db_ok = True
        except:
            pass
            
        # 2. TG status
        tg_ok = False
        try:
            url_tg = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe"
            res_tg = requests.get(url_tg, timeout=5)
            if res_tg.status_code == 200:
                tg_ok = True
        except:
            pass
            
        # 3. Data Provider status
        data_provider_ok = False
        try:
            df_test = download_market_data("EURUSD=X", "15m", period="1d")
            if not df_test.empty:
                data_provider_ok = True
        except:
            pass
            
        # 4. Winrate and count for last 6 hours
        total_6h = 0
        wr_6h = 0.0
        try:
            tz_ry = pytz.timezone("Asia/Riyadh")
            now_ry = datetime.datetime.now(tz_ry)
            six_hours_ago = now_ry - datetime.timedelta(hours=6)
            six_hours_ago_utc = six_hours_ago.astimezone(pytz.utc).isoformat()
            res_6h = supabase_client.table("signals").select("*").gte("time", six_hours_ago_utc).execute()
            if res_6h.data:
                sigs_6h = res_6h.data
                total_6h = len(sigs_6h)
                resolved_6h = [s for s in sigs_6h if s["status"] in ["WIN", "LOSS"]]
                wins_6h = sum(1 for s in resolved_6h if s["status"] == "WIN")
                wr_6h = (wins_6h / len(resolved_6h) * 100) if resolved_6h else 0.0
        except Exception as e_6h:
            print(f"Error calculating 6h stats: {e_6h}")
            
        active_provider = settings_manager.get_active_data_source()
        active_host = settings_manager.get_active_host()
        
        status_msg = "🟢 <b>SYSTEM OK: Scanner Alive</b>\n\n" \
                     f"• Supabase DB: {'Connected' if db_ok else 'FAILED'}\n" \
                     f"• Data Provider: {active_provider} ({'Online' if data_provider_ok else 'OFFLINE'})\n" \
                     f"• Designated Server: {active_host}\n" \
                     f"• Telegram Bot: {'Valid' if tg_ok else 'INVALID'}\n" \
                     f"• Last 6H: {total_6h} Signals\n" \
                     f"• WR: <b>{wr_6h:.1f}%</b>"
                     
        send_telegram_alert(status_msg)
        print("[DIAGNOSTICS] 6H Heartbeat successfully sent.")
    except Exception as e:
        print(f"Error sending diagnostics heartbeat: {e}")

def send_hourly_summary():
    if supabase_client is None:
        return
    try:
        import datetime
        import pytz
        import pandas as pd
        
        tz_ry = pytz.timezone("Asia/Riyadh")
        now_ry = datetime.datetime.now(tz_ry)
        start_time_ry = now_ry - datetime.timedelta(hours=1)
        start_time_utc = start_time_ry.astimezone(pytz.utc).isoformat()
        
        res = supabase_client.table("signals").select("*").gte("time", start_time_utc).order("time", desc=True).execute()
        signals = res.data if res.data else []
        
        period_str = f"{start_time_ry.strftime('%I:%M %p')} - {now_ry.strftime('%I:%M %p')}"
        
        msg = f"🕒 <b>HOURLY TRADING REPORT</b>\n"
        msg += f"⏱️ <b>Period:</b> <code>{period_str}</code> (Jeddah Time)\n\n"
        
        for tf in ["1m", "5m", "15m"]:
            tf_display = "1 Min" if tf == "1m" else ("5 Min" if tf == "5m" else "15 Min")
            tf_sigs = [s for s in signals if s["timeframe"].upper() == tf.upper()]
            
            wins = sum(1 for s in tf_sigs if s["status"] == "WIN")
            losses = sum(1 for s in tf_sigs if s["status"] in ["LOSS", "TIE"])
            ties = sum(1 for s in tf_sigs if s["status"] == "TIE")
            total_wl = wins + losses
            winrate = (wins / total_wl) * 100 if total_wl > 0 else 0.0
            
            msg += f"<b>{tf_display} Trades</b> ({wins}W - {losses}L | {winrate:.1f}%):\n"
            if tf_sigs:
                for sig in tf_sigs:
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
                    conf_val = sig.get("confirmations", "N/A")
                    strength_val = sig.get("strength", "NORMAL")
                    expiry_val = "15m Exp" if strength_val == "STRONG" else "5m Exp"
                    msg += f"• <code>{time_str}</code> | <b>{pair_clean}</b> | {status_emoji} | <i>{conf_val} ({strength_val} - {expiry_val})</i>\n"
            else:
                msg += "<i>No trades triggered.</i>\n"
            msg += "\n"
            
        send_telegram_alert(msg)
        print(f"[SUMMARY] Hourly summary successfully sent for {period_str} AST.")
    except Exception as e:
        print(f"Error generating hourly summary: {e}")

def get_account_balance():
    balance_file = "account_balance.txt"
    if os.path.exists(balance_file):
        try:
            with open(balance_file, "r") as f:
                return float(f.read().strip())
        except Exception:
            pass
    return 1000.00

def update_account_balance(change):
    balance_file = "account_balance.txt"
    current = get_account_balance()
    new_balance = current + change
    try:
        with open(balance_file, "w") as f:
            f.write(f"{new_balance:.2f}")
    except Exception as e:
        print(f"Failed to save balance: {e}")
    return new_balance

def resolve_pending_signals():
    pending_signals = fetch_pending_signals()
    if not pending_signals:
        return
        
    print(f"Found {len(pending_signals)} PENDING signals in database to check...")
    
    # Group pending signals by pair/timeframe to minimize yfinance downloads
    grouped = {}
    for sig in pending_signals:
        key = (sig["pair"], sig["timeframe"])
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(sig)
        
    for (pair, timeframe), sigs in grouped.items():
        try:
            # Download latest data to verify exit candle prices
            tf_lower = timeframe.lower()
            lookback = "2d" if tf_lower == "5m" else ("5d" if tf_lower == "15m" else "1d")
            df = download_market_data(pair, tf_lower, period=lookback)
            if df.empty:
                continue
                
            for sig in sigs:
                now_utc = datetime.datetime.now(pytz.utc)
                
                # Parse exit_time from Supabase (typically returned as UTC ISO string)
                exit_time_raw = pd.to_datetime(sig["exit_time"])
                exit_time_utc = exit_time_raw.tz_convert(pytz.utc) if exit_time_raw.tzinfo else pytz.utc.localize(exit_time_raw)
                
                # Calculate when the exit candle has actually closed
                delta_t = (datetime.timedelta(minutes=1) if tf_lower == "1m" else (datetime.timedelta(minutes=5) if tf_lower == "5m" else datetime.timedelta(minutes=15)))
                actual_close_time_utc = exit_time_utc + delta_t
                
                if now_utc > actual_close_time_utc:
                    # Let's locate the closest candle matching exit time in index
                    # Match index by localizing yfinance index to UTC
                    df_utc_index = df.index.tz_convert(pytz.utc) if df.index.tzinfo else df.index.map(pytz.utc.localize)
                    
                    # Target index
                    match_mask = (df_utc_index >= exit_time_utc)
                    if match_mask.any():
                        # Find the first index where timestamp is >= exit time (the exit candle closed price)
                        match_idx = np.where(match_mask)[0][0]
                        exit_price = float(df.iloc[match_idx]['Close'])
                        entry_price = float(sig["entry_price"])
                        
                        status = "TIE"
                        if sig["type"] == "CALL":
                            if exit_price > entry_price:
                                status = "WIN"
                            elif exit_price < entry_price:
                                status = "LOSS"
                        elif sig["type"] == "PUT":
                            if exit_price < entry_price:
                                status = "WIN"
                            elif exit_price > entry_price:
                                status = "LOSS"
                                
                        update_signal_in_db(sig["id"], exit_price, status)
                        update_trade_log_in_db(sig["id"], status)
                        
                        # Expiry description
                        expiry_desc = timeframe
                        
                        # Balance calculations (Stake = $10, Win Payout = +1.80p, Loss = -1.00p)
                        if status == "WIN":
                            res_label = "WIN +1.80p"
                            profit_label = "+$18.00"
                            balance_change = 8.00  # Payout $18.00 minus $10.00 stake = $8.00 profit
                        else:
                            res_label = "LOSS -1.00p"
                            profit_label = "-$10.00"
                            balance_change = -10.00
                            
                        new_balance = update_account_balance(balance_change)
                        
                        # Format and send Telegram Completed Signal alert
                        res_msg = f"🏁 <b>TRADE COMPLETED</b>\n\n" \
                                  f"<b>Pair:</b> {sig['pair'].replace('=X', '')}\n" \
                                  f"<b>Direction:</b> {sig['type']}\n" \
                                  f"<b>Result:</b> {res_label}\n" \
                                  f"<b>Profit:</b> {profit_label}\n" \
                                  f"<b>Balance:</b> ${new_balance:.2f}"
                        send_telegram_alert(res_msg)
                    elif (now_utc - exit_time_utc).total_seconds() > 3600:
                        # Timeout unresolved old signals to prevent stuck pending items
                        update_signal_in_db(sig["id"], None, "TIE")
                        update_trade_log_in_db(sig["id"], "TIE")
                        
        except Exception as e:
            print(f"Error resolving pending signals for {pair} [{timeframe}]: {e}")

# ----------------- MAIN LOOP -----------------
if __name__ == "__main__":
    print("====================================================")
    print("[START] BINARY PRO 24/7 CENTRAL SCANNER STARTING")
    print(f"Pairs: {', '.join(RADAR_PAIRS)}")
    print(f"Timeframes: {', '.join(TIMEFRAMES)}")
    print("====================================================")
    
    send_telegram_alert("🟢 <b>Central Scanner Bot Online</b>\nRunning 24/7 scans on all pairs/timeframes.")
    
    # Warm up: run once immediately
    resolve_pending_signals()
    
    while True:
        try:
            # Check Active Host Setting to prevent duplicate alerts
            active_host = settings_manager.get_active_host()
            local_host = "Render" if os.environ.get("RENDER") == "true" else "AWS"
            
            if active_host != local_host:
                print(f"[HOST CONTROL] Standby mode. Active host is set to '{active_host}', but local is '{local_host}'. Skipping scan.")
                time.sleep(15)
                continue
                
            loop_start = time.time()
            
            # Scan each pair across each timeframe
            for timeframe in TIMEFRAMES:
                for pair in RADAR_PAIRS:
                    process_market_signals(pair, timeframe)
                    # Speed up scan for Deriv WebSocket (no rate limit issues), throttle yfinance
                    active_source = settings_manager.get_active_data_source()
                    throttle = 0.1 if active_source == "Deriv WebSocket" else 1.5
                    time.sleep(throttle)
            
            # Resolve pending items
            resolve_pending_signals()
            
            # Check for Debug Mode Telegram Heartbeat
            debug_mode = os.environ.get("DEBUG_MODE", "FALSE").upper() == "TRUE"
            if debug_mode:
                now_time = datetime.datetime.now()
                if LAST_DEBUG_REPORT_TIME is None or (now_time - LAST_DEBUG_REPORT_TIME).total_seconds() >= 900:
                    LAST_DEBUG_REPORT_TIME = now_time
                    three_score_count = sum(1 for p, score in LAST_SCAN_SCORES.items() if score == 3)
                    ast_tz = pytz.timezone("Asia/Riyadh")
                    ast_now = now_time.astimezone(ast_tz) if now_time.tzinfo else pytz.utc.localize(now_time).astimezone(ast_tz)
                    time_ast_str = ast_now.strftime("%I:%M %p AST")
                    debug_msg = f"ℹ️ <b>Bot Alive - Scanning {len(RADAR_PAIRS)} pairs.</b>\n" \
                                f"Last scan time: {time_ast_str}\n" \
                                f"Signals found with 3/5 score: {three_score_count}"
                    send_telegram_alert(debug_msg)
            
            # Check current time in Saudi Arabia (Jeddah/Riyadh AST)
            import pytz
            ast_tz = pytz.timezone("Asia/Riyadh")
            now_ast = datetime.datetime.now(ast_tz)
            
            # 1. Hourly Summary Trigger (at the start of every hour)
            hour_key = now_ast.strftime("%Y-%m-%d-%H")
            if now_ast.minute == 0 and LAST_HOURLY_SENT_HOUR != hour_key:
                send_hourly_summary()
                LAST_HOURLY_SENT_HOUR = hour_key
                
            # 2. Daily Summary Trigger (at 9:00 PM Saudi Arabia Time)
            date_key = now_ast.strftime("%Y-%m-%d")
            if now_ast.hour == 21 and now_ast.minute == 0 and LAST_DAILY_SENT_DATE != date_key:
                send_daily_summary()
                LAST_DAILY_SENT_DATE = date_key

            # 3. 6-Hour Diagnostics Heartbeat Trigger
            if LAST_DIAGNOSTICS_SENT_TIME is None or (now_ast - LAST_DIAGNOSTICS_SENT_TIME).total_seconds() >= 21600:
                send_diagnostics_heartbeat()
                LAST_DIAGNOSTICS_SENT_TIME = now_ast
            
            # Target 30 second refresh loop
            elapsed = time.time() - loop_start
            sleep_duration = max(5.0, 30.0 - elapsed)
            time.sleep(sleep_duration)
            
        except KeyboardInterrupt:
            print("\nShutting down scanner...")
            break
        except Exception as e:
            print(f"Main loop error: {e}")
            time.sleep(15)
