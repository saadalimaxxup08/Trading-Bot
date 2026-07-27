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
APP_URL = os.environ.get("APP_URL", "http://localhost:8501/")

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

# Start background scanner thread in the cloud automatically
@st.cache_resource
def start_background_scanner():
    import threading
    import time
    import worker
    import pytz
    
    def scanner_thread_func():
        print("[START] 24/7 Cloud Background Scanner Active")
        import datetime
        last_daily_sent_date = None
        last_hourly_sent_hour = None
        while True:
            try:
                # Reload environment variables in case they were updated via UI/save
                from dotenv import load_dotenv
                current_dir = os.path.dirname(os.path.abspath(__file__))
                env_path = os.path.join(current_dir, ".env")
                load_dotenv(dotenv_path=env_path, override=True)
                
                # Re-read tokens from env so that worker updates its tokens
                worker.TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
                worker.TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
                
                # Run the scanning process using high-speed parallel batch downloading
                for timeframe in ["1m", "5m", "15m"]:
                    lookback = "2d" if timeframe == "5m" else ("5d" if timeframe == "15m" else "1d")
                    try:
                        # Fetch all tickers in parallel in a single HTTP request (extremely fast)
                        df_batch = yf.download(worker.RADAR_PAIRS, period=lookback, interval=timeframe, group_by="ticker", progress=False, threads=True)
                        if not df_batch.empty:
                            for pair in worker.RADAR_PAIRS:
                                if len(worker.RADAR_PAIRS) > 1 and pair in df_batch.columns.get_level_values(0):
                                    df_pair = df_batch[pair].dropna()
                                else:
                                    df_pair = df_batch.dropna()
                                worker.process_market_signals_prefetched(pair, timeframe, df_pair)
                    except Exception as e:
                        print(f"Batch download error for {timeframe}: {e}")
                    time.sleep(1.0)
                
                worker.resolve_pending_signals()
                
                # Check current time in Saudi Arabia (Jeddah/Riyadh)
                tz_ry = pytz.timezone("Asia/Riyadh")
                now_ry = datetime.datetime.now(tz_ry)
                
                # 1. Hourly Summary Trigger (at the start of every hour, e.g., 5:00 PM, 6:00 PM)
                hour_key = now_ry.strftime("%Y-%m-%d-%H")
                if now_ry.minute == 0 and last_hourly_sent_hour != hour_key:
                    worker.send_hourly_summary()
                    last_hourly_sent_hour = hour_key
                
                # 2. Daily Summary Trigger (at 9:00 PM Saudi Arabia Time)
                date_key = now_ry.strftime("%Y-%m-%d")
                if now_ry.hour == 21 and now_ry.minute == 0 and last_daily_sent_date != date_key:
                    worker.send_daily_summary()
                    last_daily_sent_date = date_key
                
                time.sleep(10)
            except Exception as e:
                print(f"Background scanner loop error: {e}")
                time.sleep(15)
                
    thread = threading.Thread(target=scanner_thread_func, daemon=True)
    thread.start()
    return thread

if supabase_client is not None:
    start_background_scanner()

def fetch_signals_from_db(pair, timeframe):
    if supabase_client is None:
        return []
    try:
        res = supabase_client.table("signals").select("*").eq("pair", pair).eq("timeframe", timeframe).order("time", desc=True).limit(50).execute()
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
                        "time": event_time.astimezone(pytz.timezone("Asia/Riyadh")).strftime("%I:%M %p AST")
                    })
            except Exception:
                continue
    return blocked, active_news_events

# ----------------- SESSION FILTER MODULE -----------------
def check_session_filter(enabled=True):
    if not enabled:
        return True, ""
    
    pkt = pytz.timezone('Asia/Riyadh')
    now_pkt = datetime.datetime.now(pkt)
    current_time = now_pkt.time()
    
    start_time = datetime.time(12, 0)
    end_time = datetime.time(23, 0)
    
    in_session = start_time <= current_time <= end_time
    time_str = now_pkt.strftime("%I:%M %p AST")
    
    return in_session, f"Current AST: {time_str} (Bot scans only: 12:00 PM - 11:00 PM AST)"

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
timeframe_map = {"1 Minute": "1m", "5 Minutes": "5m", "15 Minutes": "15m"}
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
    lookback = "2d" if tf == "5m" else ("5d" if tf == "15m" else "1d")
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

# Synchronize signal history from Supabase for the active pair and timeframe on every rerun
if supabase_client is not None and "supabase_user" in st.session_state:
    st.session_state.signal_history = fetch_signals_from_db(active_pair, timeframe)
    
    # Real-time alert triggers on new central signals
    if st.session_state.signal_history:
        latest_sig = st.session_state.signal_history[0]
        latest_sig_id = latest_sig["id"]
        
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

# Title
st.title("⚡ BINARY PRO SCANNER V3")
st.markdown("### `VIP-LEVEL TRADING STATION` | **ANTI-REPAINT**")
st.info("🟢 **Centralized Sync Mode:** Dashboard is synchronized with the central 24/7 background worker.")

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
col_reset_losses, col_clear_db = st.sidebar.columns(2)
with col_reset_losses:
    if st.button("♻️ Reset Losses", use_container_width=True):
        st.session_state.daily_losses = 0
        st.rerun()
with col_clear_db:
    if st.button("🗑️ Clear DB Logs", use_container_width=True, help="Clears historical signals from Supabase database"):
        if supabase_client is not None:
            try:
                supabase_client.table("signals").delete().neq("id", "").execute()
                st.sidebar.success("Database logs cleared!")
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Failed to clear: {e}")

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
            test_text = "<b>🔔 BINARY PRO SCANNER V3</b>\n\nThis is a test alert to verify your Telegram Bot connection. The bot is working properly! 🟢"
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
                    tf_sigs = [s for s in signals if s["timeframe"] == tf]
                    wins = sum(1 for s in tf_sigs if s["status"] == "WIN")
                    losses = sum(1 for s in tf_sigs if s["status"] == "LOSS")
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
        border_color = "#3b82f6" if is_selected else "#374151"
        bg_color = "rgba(59, 130, 246, 0.15)" if is_selected else "#111827"
        shadow = "box-shadow: 0 0 10px rgba(59, 130, 246, 0.5);" if is_selected else ""
        
        # Badges
        trend_text = "🟢 BULLISH" if pair_info["trend"] == "UP" else ("🔴 BEARISH" if pair_info["trend"] == "DOWN" else "⚪ NEUTRAL")
        status_bg = "#15803d" if pair_info["status"] == "TRADE NOW" else "#374151"
        
        rt_val = st.query_params.get("rt", "")
        link = f"/?pair={pair_ticker}"
        if rt_val:
            link += f"&rt={rt_val}"
            
        card_html = f'<a href="{link}" target="_self" style="text-decoration: none; color: inherit; display: inline-block;">'
        card_html += f'<div style="background-color: {bg_color}; border: 2px solid {border_color}; padding: 12px; border-radius: 8px; min-width: 140px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.2); {shadow} transition: transform 0.2s;">'
        card_html += f'<div style="font-weight: bold; font-size: 0.85rem; color: #f8fafc; margin-bottom: 4px;">{pair_name}</div>'
        card_html += f'<div style="font-size: 0.75rem; font-weight: bold; margin-bottom: 8px;">{trend_text}</div>'
        card_html += f'<div style="background-color: {status_bg}; color: #ffffff; font-size: 0.65rem; font-weight: bold; padding: 3px 8px; border-radius: 4px; display: inline-block;">{pair_info["status"]}</div>'
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
    tab_live, tab_tv, tab_backtest = st.tabs(["📈 STATION CHART (Indicators & Alerts)", "🖥️ TRADINGVIEW WIDGET", "🧪 SYSTEM BACKTEST"])
    
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

# RIGHT COLUMN - LIVE COMPACT SIGNAL LOGS & METRICS
with col_right:
    st.markdown("## 📡 LOGS & STATS")
    
    if st.session_state.daily_losses >= 3:
        st.error("🚨 STOP TRADING TODAY! DAILY MAX 3 LOSS REACHED.")
        st.session_state.scanning = False
        
    tab_active, tab_overall = st.tabs(["🎯 ACTIVE PAIR", "📊 OVERALL ANALYTICS"])
    
    with tab_active:
        st.caption(f"Signal Audit: {active_pair.replace('=X','')} [{timeframe}]")
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
                        
                    time_str = sig["time"].astimezone(pytz.timezone("Asia/Riyadh")).strftime("%I:%M %p")
                    
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
                
    with tab_overall:
        st.caption("All-Time Performance & Timeframe Breakdown")
        
        # Load all signals across all pairs and timeframes
        all_signals = fetch_all_signals_from_db(limit=200)
        
        with st.container(height=450):
            if all_signals:
                # 1. TIMEFRAME STATS BREAKDOWN TABLE
                stats = {}
                for tf in ["1m", "5m", "15m"]:
                    tf_signals = [s for s in all_signals if s["timeframe"] == tf]
                    wins = sum(1 for s in tf_signals if s["status"] == "WIN")
                    losses = sum(1 for s in tf_signals if s["status"] == "LOSS")
                    ties = sum(1 for s in tf_signals if s["status"] == "TIE")
                    total_wl = wins + losses
                    winrate = (wins / total_wl) * 100 if total_wl > 0 else 0.0
                    stats[tf] = {
                        "total": len(tf_signals),
                        "wins": wins,
                        "losses": losses,
                        "winrate": winrate
                    }
                
                html_stats_table = """
                <h5 style="margin: 0 0 10px 0; font-size:0.85rem; color:#94a3b8; font-weight:600;">⏱️ STATS BY TIMEFRAME</h5>
                <table style="width:100%; border-collapse: collapse; text-align: left; background-color: #111827; color:#e5e7eb; border-radius: 8px; overflow: hidden; font-size:0.75rem; margin-bottom: 15px;">
                    <thead>
                        <tr style="background-color: #1f2937; border-bottom: 2px solid #374151;">
                            <th style="padding: 6px 8px;">TF</th>
                            <th style="padding: 6px 8px;">Signals</th>
                            <th style="padding: 6px 8px;">W / L</th>
                            <th style="padding: 6px 8px;">Accuracy</th>
                        </tr>
                    </thead>
                    <tbody>
                """
                for tf in ["1m", "5m", "15m"]:
                    tf_display = "1 Min" if tf == "1m" else ("5 Min" if tf == "5m" else "15 Min")
                    color_acc = "#4caf50" if stats[tf]["winrate"] >= 60 else ("#ff9800" if stats[tf]["winrate"] >= 40 else "#ff1744")
                    html_stats_table += f"""
                        <tr style="border-bottom: 1px solid #374151;">
                            <td style="padding: 6px 8px; font-weight:bold;">{tf_display}</td>
                            <td style="padding: 6px 8px;">{stats[tf]["total"]}</td>
                            <td style="padding: 6px 8px; color:#a5d6a7;">{stats[tf]["wins"]}W <span style="color:#ef9a9a;">{stats[tf]["losses"]}L</span></td>
                            <td style="padding: 6px 8px; font-weight:bold; color:{color_acc};">{stats[tf]["winrate"]:.1f}%</td>
                        </tr>
                    """
                html_stats_table += "</tbody></table>"
                st.markdown(html_stats_table, unsafe_allow_html=True)
                
                # Visual block grid for each timeframe (like calendar blocks)
                st.markdown("<h5 style='margin: 15px 0 10px 0; font-size:0.85rem; color:#94a3b8; font-weight:600;'>📊 VISUAL TRADES FEED</h5>", unsafe_allow_html=True)
                
                for tf in ["1m", "5m", "15m"]:
                    tf_signals = [s for s in all_signals if s["timeframe"] == tf][:8] # Show latest 8 trades in a compact grid
                    tf_display = "1 Min" if tf == "1m" else ("5 Min" if tf == "5m" else "15 Min")
                    
                    st.markdown(f"<div style='font-size:0.75rem; font-weight:bold; color:#94a3b8; margin-top:5px;'>⏱️ {tf_display} Feed</div>", unsafe_allow_html=True)
                    if tf_signals:
                        html_blocks = '<div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 5px; margin-bottom: 15px;">'
                        for sig in tf_signals:
                            bg, border, text, status = "#37474f", "#455a64", "#cfd8dc", "TIE"
                            if sig["status"] == "WIN":
                                bg, border, text, status = "#1b5e20", "#2e7d32", "#a5d6a7", "WIN"
                            elif sig["status"] == "LOSS":
                                bg, border, text, status = "#b71c1c", "#c62828", "#ef9a9a", "LOSS"
                            elif sig["status"] == "PENDING":
                                bg, border, text, status = "#e65100", "#f57c00", "#ffe0b2", "PEND"
                                
                            time_str = sig["time"].astimezone(pytz.timezone("Asia/Riyadh")).strftime("%I:%M %p")
                            pair_clean = sig["pair"].replace("=X", "").replace("-USD", "/USD")
                            
                            html_blocks += f"""
                            <div style="background-color: {bg}; color: {text}; border: 1px solid {border}; padding: 6px 8px; border-radius: 6px; font-size: 0.65rem; text-align: center; width: 23%; min-width: 65px; box-sizing: border-box; box-shadow: 0 2px 4px rgba(0,0,0,0.15);">
                                <div style="font-weight: bold; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{pair_clean}</div>
                                <div style="font-size: 0.55rem; opacity: 0.85;">{time_str}</div>
                                <div style="font-weight: bold; font-size: 0.6rem; margin-top: 2px;">{status}</div>
                            </div>
                            """
                        html_blocks += "</div>"
                        st.markdown(html_blocks, unsafe_allow_html=True)
                    else:
                        st.markdown("<div style='font-size:0.7rem; color:#64748b; margin-bottom:15px;'>No signals for this timeframe yet.</div>", unsafe_allow_html=True)
                
                # 2. LATEST 10 GLOBAL SIGNALS FEED
                html_global_table = """
                <h5 style="margin: 15px 0 10px 0; font-size:0.85rem; color:#94a3b8; font-weight:600;">🌍 LATEST GLOBAL SIGNALS</h5>
                <table style="width:100%; border-collapse: collapse; text-align: left; background-color: #111827; color:#e5e7eb; border-radius: 8px; overflow: hidden; font-size:0.75rem;">
                    <thead>
                        <tr style="background-color: #1f2937; border-bottom: 2px solid #374151;">
                            <th style="padding: 6px 8px;">Time</th>
                            <th style="padding: 6px 8px;">Pair</th>
                            <th style="padding: 6px 8px;">TF</th>
                            <th style="padding: 6px 8px;">Type</th>
                            <th style="padding: 6px 8px;">Status</th>
                        </tr>
                    </thead>
                    <tbody>
                """
                for sig in all_signals[:10]:
                    badge_type = f"<span class='badge badge-call' style='font-size:0.6rem; padding: 2px 6px;'>CALL</span>" if sig["type"] == "CALL" else f"<span class='badge badge-put' style='font-size:0.6rem; padding: 2px 6px;'>PUT</span>"
                    badge_status = ""
                    if sig["status"] == "WIN":
                        badge_status = "<span class='badge badge-win' style='font-size:0.6rem; padding: 2px 6px;'>WIN</span>"
                    elif sig["status"] == "LOSS":
                        badge_status = "<span class='badge badge-loss' style='font-size:0.6rem; padding: 2px 6px;'>LOSS</span>"
                    elif sig["status"] == "TIE":
                        badge_status = "<span class='badge badge-tie' style='font-size:0.6rem; padding: 2px 6px;'>TIE</span>"
                    else:
                        badge_status = "<span class='badge badge-pending' style='font-size:0.6rem; padding: 2px 6px;'>PEND</span>"
                    
                    time_str = sig["time"].astimezone(pytz.timezone("Asia/Riyadh")).strftime("%I:%M %p")
                    pair_clean = sig["pair"].replace("=X", "").replace("-USD", "/USD")
                    
                    html_global_table += f"""
                        <tr style="border-bottom: 1px solid #374151;">
                            <td style="padding: 6px 8px;">{time_str}</td>
                            <td style="padding: 6px 8px; font-weight:bold;">{pair_clean}</td>
                            <td style="padding: 6px 8px;">{sig["timeframe"]}</td>
                            <td style="padding: 6px 8px;">{badge_type}</td>
                            <td style="padding: 6px 8px;">{badge_status}</td>
                        </tr>
                    """
                html_global_table += "</tbody></table>"
                st.markdown(html_global_table, unsafe_allow_html=True)
            else:
                st.write("No historical signals recorded in the database yet.")

# Autorefresh script (30 seconds) using native sleep and rerun to prevent browser reload session loss
if supabase_client is not None and "supabase_user" in st.session_state and st.session_state.scanning:
    import time
    time.sleep(30)
    st.rerun()
