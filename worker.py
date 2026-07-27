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

# Load env using absolute path of current folder
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, ".env")
load_dotenv(dotenv_path=env_path)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Tickers & Pairs list - Matches app.py
RADAR_PAIRS = [
    "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X", "USDCHF=X", 
    "EURGBP=X", "GBPJPY=X", "GC=F", "CL=F", "BTC-USD", "ETH-USD", "SOL-USD"
]

# Scaled volatility thresholds lookup - Matches app.py
ATR_THRESHOLDS = {
    "EURUSD=X": 0.00005,
    "GBPUSD=X": 0.00005,
    "USDJPY=X": 0.01,
    "AUDUSD=X": 0.00005,
    "USDCAD=X": 0.00005,
    "USDCHF=X": 0.00005,
    "EURGBP=X": 0.00005,
    "GBPJPY=X": 0.01,
    "GC=F": 0.2,       # Gold Futures
    "CL=F": 0.1,       # Crude Oil
    "BTC-USD": 20.0,
    "ETH-USD": 1.0,
    "SOL-USD": 0.1     # Solana
}

# Scan settings
TIMEFRAMES = ["1m", "5m", "15m"]

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

# ----------------- TELEGRAM NOTIFICATIONS -----------------
def send_telegram_alert(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
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
    return df

def check_signals(df):
    if len(df) < 50:
        df['Call_Score'] = 0
        df['Put_Score'] = 0
        return df

    macd = df['MACD']
    signal = df['MACD_Signal']
    macd_prev = macd.shift(1)
    signal_prev = signal.shift(1)
    
    macd_up_cross = (macd_prev <= signal_prev) & (macd > signal)
    macd_down_cross = (macd_prev >= signal_prev) & (macd < signal)
    
    bb_lower_touch = (df['Low'].shift(1) <= df['BB_Lower'].shift(1)) | (df['Low'] <= df['BB_Lower'])
    bb_lower_recover = df['Close'] > df['Open']
    bb_call_trigger = bb_lower_touch & bb_lower_recover
    
    bb_upper_touch = (df['High'].shift(1) >= df['BB_Upper'].shift(1)) | (df['High'] >= df['BB_Upper'])
    bb_upper_recover = df['Close'] < df['Open']
    bb_put_trigger = bb_upper_touch & bb_put_trigger_val if 'bb_put_trigger_val' in locals() else bb_upper_touch & bb_upper_recover
    
    vol = df['Volume']
    vol_prev = vol.shift(1)
    
    if (vol == 0).all():
        vol_increasing = pd.Series(True, index=df.index)
    else:
        vol_increasing = vol > vol_prev
        
    ema_call = df['EMA_50'] > df['EMA_200']
    rsi_call = df['RSI_14'] > 50
    
    ema_put = df['EMA_50'] < df['EMA_200']
    rsi_put = df['RSI_14'] < 50
    
    call_scores = (
        ema_call.astype(int) + 
        rsi_call.astype(int) + 
        macd_up_cross.astype(int) + 
        bb_call_trigger.astype(int) + 
        vol_increasing.astype(int)
    )
    
    put_scores = (
        ema_put.astype(int) + 
        rsi_put.astype(int) + 
        macd_down_cross.astype(int) + 
        bb_put_trigger.astype(int) + 
        vol_increasing.astype(int)
    )
    
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
            "patterns": sig["patterns"]
        }
        supabase_client.table("signals").insert(sig_data).execute()
        return True
    except Exception as e:
        print(f"Failed to save signal to database: {e}")
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

def process_market_signals(pair, timeframe):
    lookback = "2d" if timeframe == "5m" else ("5d" if timeframe == "15m" else "1d")
    
    try:
        df = yf.download(pair, period=lookback, interval=timeframe, progress=False, threads=False)
        if df.empty:
            return
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = calculate_indicators(df)
        df = check_signals(df)
        
        if len(df) < 2:
            return

        # Check the closed candle (index -2)
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
        
        if closed_candle['Call_Score'] >= 4:
            sig_type = "CALL"
            confirmations = closed_candle['Call_Score']
        elif closed_candle['Put_Score'] >= 4:
            sig_type = "PUT"
            confirmations = closed_candle['Put_Score']
            
        if sig_type:
            # Expiry selection default is 1 candle
            delta_t = (datetime.timedelta(minutes=1) if timeframe == "1m" else (datetime.timedelta(minutes=5) if timeframe == "5m" else datetime.timedelta(minutes=15)))
            exit_time = closed_candle_time + delta_t
            
            pattern = closed_candle['Pattern_Label']
            strength = "NORMAL"
            
            # Simple strength logic matching app.py
            if pattern:
                strength = "STRONG"
                
            new_sig = {
                "id": str(int(time.time())) + f"-{pair}-{timeframe}",
                "time": closed_candle_time,
                "pair": pair,
                "timeframe": timeframe,
                "type": sig_type,
                "entry_price": float(closed_candle['Close']),
                "exit_time": exit_time,
                "exit_price": None,
                "status": "PENDING",
                "strength": strength,
                "confirmations": f"{confirmations}/5",
                "patterns": pattern if pattern else "None"
            }
            
            success = save_signal_to_db(new_sig)
            if success:
                # Convert closed_candle_time to Pakistan timezone (Asia/Karachi)
                pkt_tz = pytz.timezone("Asia/Karachi")
                if closed_candle_time.tzinfo is not None:
                    closed_candle_time_pkt = closed_candle_time.astimezone(pkt_tz)
                else:
                    closed_candle_time_pkt = pytz.utc.localize(closed_candle_time).astimezone(pkt_tz)
                alert_time_str = closed_candle_time_pkt.strftime("%I:%M %p PKT")
                
                print(f"[SIGNAL] NEW Central Signal: {pair} [{timeframe}] {sig_type} at {alert_time_str}")
                
                # Format and send Telegram notification
                tg_text = f"🚨 <b>CENTRAL BINARY PRO V3 SIGNAL</b>\n\n" \
                          f"<b>Asset:</b> {pair.replace('=X', '')}\n" \
                          f"<b>Timeframe:</b> {timeframe}\n" \
                          f"<b>Type:</b> {'🟢 CALL' if sig_type == 'CALL' else '🔴 PUT'}\n" \
                          f"<b>Entry Price:</b> {closed_candle['Close']:.5f}\n" \
                          f"<b>Confirmations:</b> {confirmations}/5\n" \
                          f"<b>Strength:</b> {strength}\n" \
                          f"<b>Patterns:</b> {pattern if pattern else 'None'}\n" \
                          f"<b>Time:</b> {alert_time_str}\n\n" \
                          f"⚠️ <i>Auto Result evaluation will complete on next candles.</i>"
                send_telegram_alert(tg_text)
                
    except Exception as e:
        print(f"Error processing market signals for {pair} [{timeframe}]: {e}")

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
            lookback = "2d" if timeframe == "5m" else ("5d" if timeframe == "15m" else "1d")
            df = yf.download(pair, period=lookback, interval=timeframe, progress=False, threads=False)
            if df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                
            for sig in sigs:
                now_utc = datetime.datetime.now(pytz.utc)
                
                # Parse exit_time from Supabase (typically returned as UTC ISO string)
                exit_time_raw = pd.to_datetime(sig["exit_time"])
                exit_time_utc = exit_time_raw.tz_convert(pytz.utc) if exit_time_raw.tzinfo else pytz.utc.localize(exit_time_raw)
                
                if now_utc > exit_time_utc:
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
                    elif (now_utc - exit_time_utc).total_seconds() > 3600:
                        # Timeout unresolved old signals to prevent stuck pending items
                        update_signal_in_db(sig["id"], None, "TIE")
                        
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
            loop_start = time.time()
            
            # Scan each pair across each timeframe
            for timeframe in TIMEFRAMES:
                for pair in RADAR_PAIRS:
                    process_market_signals(pair, timeframe)
                    # Small throttle to prevent yfinance block during scan
                    time.sleep(1.5)
            
            # Resolve pending items
            resolve_pending_signals()
            
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
