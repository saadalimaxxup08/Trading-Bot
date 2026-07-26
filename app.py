import streamlit as st
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

from supabase import create_client, Client, ClientOptions

# Setup page config for a premium wide layout
st.set_page_config(
    page_title="Binary Pro Scanner V3 - VIP Trading Station",
    layout="wide",
    page_icon="📈",
    initial_sidebar_state="expanded"
)

# Custom premium dark styling
st.markdown("""
<style>
    /* Main Layout Styling */
    .stApp {
        background-color: #0b0e14;
        color: #e0e6ed;
    }
    .stButton>button {
        background-color: #1e88e5;
        color: white;
        border-radius: 6px;
        border: none;
        padding: 10px 24px;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #1565c0;
        transform: translateY(-2px);
    }
    /* Metric Cards Styling */
    .metric-card {
        background: rgba(30, 41, 59, 0.5);
        border-radius: 12px;
        padding: 15px;
        border: 1px solid rgba(255, 255, 255, 0.08);
        text-align: center;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.15);
        backdrop-filter: blur(10px);
    }
    .metric-title {
        font-size: 0.85rem;
        color: #94a3b8;
        margin-bottom: 5px;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .metric-value {
        font-size: 1.6rem;
        font-weight: 700;
        color: #ffffff;
    }
    /* HTML Table badges */
    .badge {
        padding: 4px 10px;
        border-radius: 4px;
        font-weight: 600;
        font-size: 0.75rem;
        text-transform: uppercase;
        display: inline-block;
        text-align: center;
    }
    .badge-win {
        background-color: #1b5e20;
        color: #a5d6a7;
        border: 1px solid #2e7d32;
    }
    .badge-loss {
        background-color: #b71c1c;
        color: #ef9a9a;
        border: 1px solid #c62828;
    }
    .badge-pending {
        background-color: #e65100;
        color: #ffe0b2;
        border: 1px solid #f57c00;
    }
    .badge-tie {
        background-color: #37474f;
        color: #cfd8dc;
        border: 1px solid #455a64;
    }
    .badge-call {
        background-color: #1b5e20;
        color: #ffffff;
        font-weight: bold;
    }
    .badge-put {
        background-color: #b71c1c;
        color: #ffffff;
        font-weight: bold;
    }
    /* Volatility Status badges for Radar */
    .badge-trade {
        background-color: #1b5e20;
        color: #a5d6a7;
        font-weight: bold;
        border: 1px solid #2e7d32;
        width: 100%;
        display: block;
    }
    .badge-wait {
        background-color: #37474f;
        color: #b0bec5;
        font-weight: bold;
        border: 1px solid #455a64;
        width: 100%;
        display: block;
    }
    .badge-trend-up {
        background-color: rgba(76, 175, 80, 0.15);
        color: #4caf50;
        border: 1px solid rgba(76, 175, 80, 0.3);
    }
    .badge-trend-down {
        background-color: rgba(244, 67, 54, 0.15);
        color: #f44336;
        border: 1px solid rgba(244, 67, 54, 0.3);
    }
    .badge-trend-neutral {
        background-color: rgba(158, 158, 158, 0.15);
        color: #9e9e9e;
        border: 1px solid rgba(158, 158, 158, 0.3);
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
    st.session_state.selected_pair = "BTC-USD"
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
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://your-project-id.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "your-supabase-anon-key-here")

def get_supabase_client():
    if not SUPABASE_URL or "your-project-id" in SUPABASE_URL or "your-supabase-anon" in SUPABASE_KEY:
        return None
    try:
        # Disable auto-refresh token and session persistence to prevent background threads hanging in Streamlit
        options = ClientOptions(auto_refresh_token=False, persist_session=False)
        return create_client(SUPABASE_URL, SUPABASE_KEY, options=options)
    except Exception:
        return None

supabase_client = get_supabase_client()

def fetch_signals_from_db(pair):
    if supabase_client is None:
        return []
    try:
        res = supabase_client.table("signals").select("*").eq("pair", pair).order("time", desc=True).limit(50).execute()
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
        supabase_client.table("signals").update(payload).eq("id", sig["id"]).execute()
    except Exception as e:
        print(f"Failed to update signal in database: {e}")

# Secure login screen check
if supabase_client is not None:
    # Check if redirect query parameters exist (passed by our JS redirect component)
    if "access_token" in st.query_params:
        access_token = st.query_params["access_token"]
        refresh_token = st.query_params.get("refresh_token", "")
        try:
            res = supabase_client.auth.set_session(access_token, refresh_token)
            if res.user:
                st.session_state.supabase_user = res.user
                st.query_params.clear()
                st.rerun()
        except Exception as e:
            st.error(f"Failed to restore magic link session: {e}")

    if "supabase_user" not in st.session_state:
        # JavaScript component to read URL hash and redirect if magic link token exists
        st.components.v1.html(
            """
            <script>
            try {
                const parentHash = window.parent.location.hash;
                if (parentHash && parentHash.includes('access_token=')) {
                    const params = new URLSearchParams(parentHash.replace('#', '?'));
                    const token = params.get('access_token');
                    const refresh = params.get('refresh_token') || '';
                    if (token) {
                        window.parent.location.href = window.parent.location.pathname + "?access_token=" + token + "&refresh_token=" + refresh;
                    }
                }
            } catch (e) {
                console.error("CORS block or error accessing parent window hash:", e);
            }
            </script>
            """,
            height=0,
            width=0
        )

        # Inject Premium Glowing Style Sheet for Login Portal
        st.markdown("""
        <style>
            /* Override background for login screen specifically */
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
            # Login Form container
            st.markdown("<div class='login-container'>", unsafe_allow_html=True)
            st.markdown("<div class='glow-title'>⚡ BINARY PRO</div>", unsafe_allow_html=True)
            st.markdown("<div style='color:#a1a1aa; font-size:0.95rem; margin-bottom:30px;'>VIP Trading Access Portal</div>", unsafe_allow_html=True)

            if not st.session_state.otp_sent:
                email_input = st.text_input("Enter Email to Login", placeholder="trader@example.com")
                st.markdown("</div>", unsafe_allow_html=True) # close container for positioning input correctly
                st.markdown("<br>", unsafe_allow_html=True)
                
                st.markdown("<div class='glow-btn'>", unsafe_allow_html=True)
                if st.button("📩 Send Magic Link", use_container_width=True):
                    if email_input:
                        try:
                            # Request Supabase OTP (triggers Magic Link email)
                            res = supabase_client.auth.sign_in_with_otp({"email": email_input})
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
                st.markdown(f"<p style='color:#a1a1aa; font-size:0.85rem;'>A secure magic login link and verification code have been sent to <b>{st.session_state.login_email}</b> (check inbox & spam folder).</p>", unsafe_allow_html=True)
                st.markdown("<p style='color:#6366f1; font-size:0.85rem; font-weight:600;'>You can click the link in your email to log in, or enter the 6-digit verification code below:</p>", unsafe_allow_html=True)
                
                otp_code = st.text_input("6-Digit Code", placeholder="123456")
                st.markdown("</div>", unsafe_allow_html=True)
                st.markdown("<br>", unsafe_allow_html=True)
                
                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    if st.button("⬅️ Change Email", use_container_width=True):
                        st.session_state.otp_sent = False
                        st.rerun()
                with col_b2:
                    if st.button("✅ Verify & Enter", use_container_width=True):
                        if otp_code:
                            try:
                                res = supabase_client.auth.verify_otp({
                                    "email": st.session_state.login_email,
                                    "token": otp_code,
                                    "type": "magiclink"
                                })
                                if res.user:
                                    st.session_state.supabase_user = res.user
                                    st.success("Access Granted!")
                                    st.rerun()
                                else:
                                    st.error("Verification failed. Invalid code.")
                            except Exception as e:
                                st.error(f"Error verifying code: {e}")
                        else:
                            st.warning("Please enter the code.")
            
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
    "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X", "USDCHF=X", 
    "EURGBP=X", "GBPJPY=X", "GC=F", "CL=F", "BTC-USD", "ETH-USD", "SOL-USD"
]

# Scaled volatility thresholds lookup
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
                        "time": event_time.astimezone(pytz.timezone("Asia/Karachi")).strftime("%I:%M %p PKT")
                    })
            except Exception:
                continue
    return blocked, active_news_events

# ----------------- SESSION FILTER MODULE -----------------
def check_session_filter(enabled=True):
    if not enabled:
        return True, ""
    
    pkt = pytz.timezone('Asia/Karachi')
    now_pkt = datetime.datetime.now(pkt)
    current_time = now_pkt.time()
    
    start_time = datetime.time(12, 0)
    end_time = datetime.time(23, 0)
    
    in_session = start_time <= current_time <= end_time
    time_str = now_pkt.strftime("%I:%M %p PKT")
    
    return in_session, f"Current PKT: {time_str} (Bot scans only: 12:00 PM - 11:00 PM PKT)"

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
    return df

# ----------------- SIGNALS & CONFIRMATIONS MODULE -----------------
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
    bb_put_trigger = bb_upper_touch & bb_upper_recover
    
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
        df_batch = yf.download(RADAR_PAIRS, period="5d", interval="15m", group_by="ticker", progress=False)
        if df_batch.empty:
            return radar_results

        for pair in RADAR_PAIRS:
            try:
                # Extract ticker subset
                if len(RADAR_PAIRS) > 1 and pair in df_batch.columns.get_level_values(0):
                    df_pair = df_batch[pair].dropna()
                else:
                    df_pair = df_batch.dropna()
                
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
        df = yf.download(pair, period=f"{days}d", interval=timeframe, progress=False)
        if df.empty:
            st.error("Failed to load historical backtest data.")
            return
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = calculate_indicators(df)
        df = check_signals(df)
        
        df_15m = yf.download(pair, period=f"{days}d", interval="15m", progress=False)
        if isinstance(df_15m.columns, pd.MultiIndex):
            df_15m.columns = df_15m.columns.get_level_values(0)
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
            
            if row['Call_Score'] >= 4:
                sig_type = "CALL"
                confirmations = row['Call_Score']
            elif row['Put_Score'] >= 4:
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
                
        total = wins + losses + ties
        winrate = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0
        
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
                
                html_table += f"""
                    <tr style="border-bottom: 1px solid #374151;">
                        <td style="padding: 10px 16px;">{sig["Time"]}</td>
                        <td style="padding: 10px 16px;">{badge_type}</td>
                        <td style="padding: 10px 16px; color: {strength_color}; font-weight: 600;">{sig["Strength"]}</td>
                        <td style="padding: 10px 16px;">{sig["Confirmations"]}</td>
                        <td style="padding: 10px 16px;">{sig["Entry"]}</td>
                        <td style="padding: 10px 16px;">{sig["Exit"]}</td>
                        <td style="padding: 10px 16px;">{badge_status}</td>
                    </tr>
                """
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
    "USDCAD=X": "USD/CAD",
    "USDCHF=X": "USD/CHF",
    "EURGBP=X": "EUR/GBP",
    "GBPJPY=X": "GBP/JPY",
    "GC=F": "GOLD (GC=F)",
    "CL=F": "Crude Oil (CL=F)",
    "BTC-USD": "BTC/USD",
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
timeframe_map = {"1 Minute": "1m", "5 Minutes": "5m"}
timeframe_sel = st.sidebar.selectbox("TIMEFRAME SELECT", list(timeframe_map.keys()), index=1)
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
    lookback = "2d" if tf == "5m" else "1d"
    try:
        df = yf.download(pair, period=lookback, interval=tf, progress=False, threads=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception:
        return pd.DataFrame()

df_live = get_live_data(active_pair, timeframe)
if not df_live.empty:
    try:
        df_live = calculate_indicators(df_live)
        df_live = check_signals(df_live)
    except Exception as e:
        st.error(f"Error calculating indicators: {e}")
else:
    st.error("Failed to load live price data from yfinance.")

# Synchronize signal history from Supabase on startup
if supabase_client is not None and "supabase_user" in st.session_state:
    if "db_signals_loaded" not in st.session_state or not st.session_state.db_signals_loaded:
        with st.spinner("Syncing signals database..."):
            loaded_signals = []
            for pair in RADAR_PAIRS:
                loaded_signals.extend(fetch_signals_from_db(pair))
            # Sort signals by timestamp descending
            loaded_signals.sort(key=lambda x: x["time"], reverse=True)
            st.session_state.signal_history = loaded_signals
            st.session_state.db_signals_loaded = True

# Auto evaluate results using cached df_live
evaluate_pending_signals(df_live, active_pair)

# Title
st.title("⚡ BINARY PRO SCANNER V3")
st.markdown("### `VIP-LEVEL TRADING STATION` | **ANTI-REPAINT**")

# Calculate live session stats
session_wins = sum(1 for sig in st.session_state.signal_history if sig["status"] == "WIN")
session_losses = sum(1 for sig in st.session_state.signal_history if sig["status"] == "LOSS")
session_ties = sum(1 for sig in st.session_state.signal_history if sig["status"] == "TIE")
session_total = session_wins + session_losses
session_winrate = (session_wins / session_total) * 100 if session_total > 0 else 0.0

# Render top stats banner
col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)
with col_stat1:
    st.markdown(f"<div class='metric-card'><div class='metric-title'>Session Wins ✅</div><div class='metric-value' style='color:#00e676;'>{session_wins}</div></div>", unsafe_allow_html=True)
with col_stat2:
    st.markdown(f"<div class='metric-card'><div class='metric-title'>Session Losses ❌</div><div class='metric-value' style='color:#ff1744;'>{session_losses}</div></div>", unsafe_allow_html=True)
with col_stat3:
    st.markdown(f"<div class='metric-card'><div class='metric-title'>Session Ties ⚪</div><div class='metric-value' style='color:#b0bec5;'>{session_ties}</div></div>", unsafe_allow_html=True)
with col_stat4:
    color_winrate = "#00e676" if session_winrate >= 60 else ("#ff9800" if session_winrate >= 40 else "#ff1744")
    st.markdown(f"<div class='metric-card'><div class='metric-title'>Session Winrate 🎯</div><div class='metric-value' style='color:{color_winrate};'>{session_winrate:.1f}%</div></div>", unsafe_allow_html=True)

st.progress(session_winrate / 100.0 if session_total > 0 else 0.0, text=f"Live Accuracy Meter: {session_winrate:.1f}% Accuracy")
st.markdown("<br>", unsafe_allow_html=True)

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

# Global Settings
st.sidebar.markdown("---")
session_filter_enabled = st.sidebar.checkbox("Session Filter (12-23 PKT)", value=True)
news_filter_enabled = st.sidebar.checkbox("News Calendar Filter", value=True)
volatility_filter_enabled = st.sidebar.checkbox("Volatility ATR Filter", value=True)

# Risk Manager
st.sidebar.markdown("---")
st.sidebar.markdown("### 💼 RISK MANAGER")
st.sidebar.markdown(f"**Daily Limit:** `Max 3 Loss`")
st.sidebar.markdown(f"**Losses Today:** `{st.session_state.daily_losses} / 3`")
if st.sidebar.button("♻️ Reset Losses"):
    st.session_state.daily_losses = 0
    st.rerun()

# Telegram Settings Panel
st.sidebar.markdown("---")
st.sidebar.markdown("### ✈️ TELEGRAM ALERTS")
tg_token = st.sidebar.text_input("Bot Token", type="password", help="Telegram Bot Token")
tg_chat_id = st.sidebar.text_input("Chat ID", type="password", help="Telegram Chat ID")

# Currency Converter Sidebar
st.sidebar.markdown("---")
st.sidebar.markdown("### 💱 CURRENCY CONVERTER")
c_from = st.sidebar.selectbox("From", ["USD", "EUR", "GBP", "JPY", "CAD", "AUD"])
c_to = st.sidebar.selectbox("To", ["PKR", "INR", "USD", "EUR", "GBP"])
c_amount = st.sidebar.number_input("Amount", value=100.0, step=10.0)

if st.sidebar.button("Convert Now"):
    converted = None
    if rates:
        try:
            converted = rates.convert(c_from, c_to, c_amount)
        except Exception:
            pass
    if converted is None:
        mock_rates = {
            ("USD", "PKR"): 278.5, ("EUR", "PKR"): 302.2, ("GBP", "PKR"): 355.0,
            ("USD", "INR"): 83.5, ("EUR", "INR"): 90.6, ("GBP", "INR"): 106.4,
            ("EUR", "USD"): 1.09, ("GBP", "USD"): 1.28, ("USD", "JPY"): 155.2
        }
        rate = mock_rates.get((c_from, c_to)) or mock_rates.get((c_to, c_from), 1.0)
        if (c_to, c_from) in mock_rates:
            rate = 1.0 / rate
        converted = c_amount * rate
    st.sidebar.success(f"{c_amount} {c_from} = {converted:.2f} {c_to}")

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
    st.rerun()

# ----------------- THREE COLUMN LAYOUT ASSEMBLY -----------------
col_left, col_center, col_right = st.columns([3, 6, 3])

# LEFT COLUMN - MARKET RADAR DASHBOARD
with col_left:
    st.markdown("## 📡 MARKET RADAR")
    st.caption("Auto 15m Trend & ATR Volatility Scanner")
    
    with st.spinner("Refreshing Radar Dashboard..."):
        radar_data = calculate_radar_data()
        
    if radar_data:
        # Wrap in scrollable container to prevent vertical stretching and keep columns aligned
        with st.container(height=450):
            # Build Table manually with streamlit columns
            st.markdown("""
            <div style="font-weight:bold; background-color:#1f2937; padding:8px; border-radius:4px; display:flex; justify-content:space-between; margin-bottom:5px; border-bottom: 2px solid #374151;">
                <div style="width:28%;">Pair</div>
                <div style="width:28%;">15m Trend</div>
                <div style="width:28%;">Status</div>
                <div style="width:16%;">Action</div>
            </div>
            """, unsafe_allow_html=True)
            
            for pair_ticker in RADAR_PAIRS:
                pair_name = pair_ticker.replace("=X", "").replace("-USD", "/USD")
                pair_info = radar_data.get(pair_ticker, {"trend": "NEUTRAL", "status": "WAIT"})
                
                trend_badge = ""
                if pair_info["trend"] == "UP":
                    trend_badge = "<span class='badge badge-trend-up'>🟢 BULLISH</span>"
                elif pair_info["trend"] == "DOWN":
                    trend_badge = "<span class='badge badge-trend-down'>🔴 BEARISH</span>"
                else:
                    trend_badge = "<span class='badge badge-trend-neutral'>⚪ NEUTRAL</span>"
                    
                status_badge = ""
                if pair_info["status"] == "TRADE NOW":
                    status_badge = "<span class='badge badge-trade'>TRADE NOW</span>"
                else:
                    status_badge = "<span class='badge badge-wait'>WAIT</span>"
                
                # Row Container
                row_col = st.columns([2.5, 2.5, 2.5, 1.5])
                
                # Highlight Selected Pair
                if pair_ticker == st.session_state.selected_pair:
                    row_col[0].markdown(f"**⚡ {pair_name}**")
                else:
                    row_col[0].markdown(f"{pair_name}")
                    
                row_col[1].markdown(trend_badge, unsafe_allow_html=True)
                row_col[2].markdown(status_badge, unsafe_allow_html=True)
                
                # Trigger Selection
                if row_col[3].button("👁️", key=f"btn_radar_{pair_ticker}", help=f"Show {pair_name} Chart"):
                    st.session_state.selected_pair = pair_ticker
                    st.rerun()
    else:
        st.error("Failed to load Market Radar batch data.")

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
                
    # Tab View for Live and Backtest
    tab_live, tab_backtest = st.tabs(["🔴 LIVE CHARTS & ALERTS", "🧪 SYSTEM BACKTEST"])
    
    with tab_live:
        # Download Active Ticker Live Data
        lookback = "5d" if timeframe == "5m" else "2d"
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
                    
                # Signal Scanning Trigger
                if st.session_state.scanning and not news_blocked and not volatility_low and st.session_state.daily_losses < 3:
                    sig_type = None
                    confirmations = 0
                    
                    if closed_candle['Call_Score'] >= 4:
                        sig_type = "CALL"
                        confirmations = closed_candle['Call_Score']
                    elif closed_candle['Put_Score'] >= 4:
                        sig_type = "PUT"
                        confirmations = closed_candle['Put_Score']
                        
                    # Handle trigger
                    if sig_type and (st.session_state.last_processed_candle != closed_candle_time):
                        st.session_state.last_processed_candle = closed_candle_time
                        
                        delta_t = (datetime.timedelta(minutes=1) if timeframe == "1m" else datetime.timedelta(minutes=5)) * expiry_candles
                        exit_time = closed_candle_time + delta_t
                        
                        pattern = closed_candle['Pattern_Label']
                        strength = "NORMAL"
                        
                        # Confluence
                        active_trend = current_radar_info["trend"]
                        if (sig_type == "CALL" and active_trend == "UP") or (sig_type == "PUT" and active_trend == "DOWN"):
                            strength = "STRONG++"
                        elif pattern:
                            strength = "STRONG"
                            
                        # Add to session history
                        new_sig = {
                            "id": str(int(time.time())),
                            "time": closed_candle_time,
                            "pair": active_pair,
                            "timeframe": timeframe,
                            "type": sig_type,
                            "entry_price": closed_candle['Close'],
                            "exit_time": exit_time,
                            "exit_price": None,
                            "status": "PENDING",
                            "strength": strength,
                            "confirmations": f"{confirmations}/5",
                            "patterns": pattern if pattern else "None"
                        }
                        st.session_state.signal_history.append(new_sig)
                        save_signal_to_db(new_sig)
                        
                        # Alerts
                        trigger_browser_beep()
                        alert_time_str = closed_candle_time.strftime("%I:%M %p PKT")
                        st.toast(f"🔥 NEW VIP SIGNAL TRIGGERED: {sig_type} at {alert_time_str}!", icon="🔊")
                        
                        # Telegram Alert
                        tg_text = f"🚨 <b>BINARY PRO SCANNER V3 SIGNAL</b>\n\n" \
                                  f"<b>Asset:</b> {active_pair}\n" \
                                  f"<b>Timeframe:</b> {timeframe_sel}\n" \
                                  f"<b>Expiry:</b> {expiry_candles} candle(s)\n" \
                                  f"<b>Type:</b> {'🟢 CALL' if sig_type == 'CALL' else '🔴 PUT'}\n" \
                                  f"<b>Entry Price:</b> {closed_candle['Close']:.5f}\n" \
                                  f"<b>Confirmations:</b> {confirmations}/5\n" \
                                  f"<b>Strength:</b> {strength}\n" \
                                  f"<b>Patterns:</b> {pattern if pattern else 'None'}\n" \
                                  f"<b>Time:</b> {alert_time_str}\n\n" \
                                  f"⚠️ <i>Auto Result evaluation will complete in {expiry_candles} candle(s) ({timeframe_sel}).</i>"
                        send_telegram_alert(tg_token, tg_chat_id, tg_text)
                
                # Render Multi-plot Plotly Chart
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
                    if sig["pair"] == active_pair and sig["timeframe"] == timeframe:
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
                
                # Autorefresh script (30 seconds)
                if st.session_state.scanning:
                    st.components.v1.html(
                        f"""
                        <script>
                        setTimeout(function() {{
                            window.parent.location.reload();
                        }}, 30000);
                        </script>
                        """,
                        height=0,
                        width=0
                    )
                    st.caption("🔄 Auto-refresh active (30s interval)")
            else:
                st.error("Empty data received for active pair.")
        except Exception as e:
            st.error(f"Error drawing chart: {e}")
            
    with tab_backtest:
        run_backtest(active_pair, timeframe)

# RIGHT COLUMN - LIVE COMPACT SIGNAL LOGS & METRICS
with col_right:
    st.markdown("## 📡 LOGS FEED")
    st.caption(f"Real-Time Signal Audit: {active_pair.replace('=X','')}")
    
    if st.session_state.daily_losses >= 3:
        st.error("🚨 STOP TRADING TODAY! DAILY MAX 3 LOSS REACHED.")
        st.session_state.scanning = False
        
    filtered_log = [sig for sig in st.session_state.signal_history if sig["pair"] == active_pair]
    
    # Wrap logs feed inside a scrollable container matching other columns
    with st.container(height=450):
        if filtered_log:
            html_right_table = """
            <table style="width:100%; border-collapse: collapse; text-align: left; background-color: #111827; color:#e5e7eb; border-radius: 8px; overflow: hidden; font-size:0.8rem;">
                <thead>
                    <tr style="background-color: #1f2937; border-bottom: 2px solid #374151;">
                        <th style="padding: 8px 10px;">Time</th>
                        <th style="padding: 8px 10px;">Type</th>
                        <th style="padding: 8px 10px;">Confirmations</th>
                        <th style="padding: 8px 10px;">Status</th>
                    </tr>
                </thead>
                <tbody>
            """
            for sig in reversed(filtered_log[-10:]):
                badge_type = f"<span class='badge badge-call' style='font-size:0.7rem;'>CALL</span>" if sig["type"] == "CALL" else f"<span class='badge badge-put' style='font-size:0.7rem;'>PUT</span>"
                
                badge_status = ""
                if sig["status"] == "WIN":
                    badge_status = "<span class='badge badge-win' style='font-size:0.7rem;'>WIN</span>"
                elif sig["status"] == "LOSS":
                    badge_status = "<span class='badge badge-loss' style='font-size:0.7rem;'>LOSS</span>"
                elif sig["status"] == "TIE":
                    badge_status = "<span class='badge badge-tie' style='font-size:0.7rem;'>TIE</span>"
                else:
                    badge_status = "<span class='badge badge-pending' style='font-size:0.7rem;'>PENDING</span>"
                    
                time_str = sig["time"].strftime("%I:%M %p")
                
                html_right_table += f"""
                    <tr style="border-bottom: 1px solid #374151;">
                        <td style="padding: 8px 10px;">{time_str}</td>
                        <td style="padding: 8px 10px;">{badge_type}</td>
                        <td style="padding: 8px 10px; font-weight:600;">{sig["confirmations"]}</td>
                        <td style="padding: 8px 10px;">{badge_status}</td>
                    </tr>
                """
            html_right_table += "</tbody></table>"
            st.markdown(html_right_table, unsafe_allow_html=True)
            
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
