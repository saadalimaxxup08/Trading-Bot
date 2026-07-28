# Binary Pro Scanner V4 (Sniper Edition) - AI Instruction Manual

This document serves as the project's permanent "brain". It defines the system architecture, trading strategy, and behavioral rules for any AI agent working on this codebase.

---

## 1. System Overview & Architecture

* **Worker (`worker.py`):** Runs 24/7 in the background. Downloads yfinance batch data, calculates indicators, evaluates signals, sends Telegram notifications, and updates the Supabase database.
* **Streamlit UI (`app.py`):** Provides a visual dashboard, live station chart, and backtester. It runs the background scanner thread using a shared state system (`GLOBAL_SETTINGS`).
* **Database (Supabase):** Stores signal history, pending trades, diagnostics, and final outcomes (WIN/LOSS/TIE).
* **Alert System (Telegram):** Broadcasts Pre-Alerts (20s before close), Final Signals (confirmations at close), Cancel Alerts (if failed at close), and Completed Results (WIN/LOSS payouts with simulated account balances).

---

## 2. Active Technical Strategy (V4 Sniper Matrix)

Every signal must satisfy the core 5-Step Matrix and 4 V4 Sniper filters:

1. **MACD Crossover:** MACD crosses Signal Line (Up for CALL, Down for PUT).
2. **Bollinger Band Rejection:** Price touches and rejects Lower BB (for CALL) or Upper BB (for PUT).
3. **RSI Strict Zone:** RSI must be between `40-55` (for CALL) and `45-60` (for PUT).
4. **EMA200 Slope Filter:** Price is above EMA200 and EMA200 slope > 0 (for CALL). Price is below EMA200 and EMA200 slope < 0 (for PUT).
5. **Pattern Filter:** Marubozu, Hammer, and Engulfing patterns weight the score. Doji, Shooting Star, and 3 Crows candles block entries.

### V4 Sniper Filters:
* **ATR Spike Block:** Blocks signal if active candle range `(High - Low) > (ATR_14 * 2.5)`.
* **Pivot S/R Confirmation:** Active BB must be within 10 pips of the 20-candle rolling Swing Low (CALL) or Swing High (PUT).
* **MTF Trend Shield:** 5m signals are blocked if the 15m trend does not align (`EMA_50 > EMA_200` for CALL).

---

## 3. Operations & Configuration

* **Active Pairs:** EURUSD=X, GBPUSD=X, USDJPY=X, AUDUSD=X, USDCAD=X, USDCHF=X, EURGBP=X, EURJPY=X (8 Forex Majors).
* **Timeframes:** Signal on **5M** only. Filter on **15M**.
* **Active Sessions:** Karachi Timezone (PKT) **12:00 PM to 12:00 AM PKT**. Scanning is automatically paused outside these hours.
* **Expiry Rules:** Standard expiry is **5 Minutes**. STRONG++ trades (Marubozu + MTF confirmed) use **15 Minutes** expiry.

---

## 4. Coding & Maintenance Constraints

* **Timezones:** All trade times in database must be UTC. Telegram alerts must show dual PKT and UTC headers.
* **Tie as Loss:** All draw/tie results must be treated as LOSS in stats calculations to keep performance metrics conservative.
* **Balance Simulation:** Simulate stake payouts (Stake = $10, Win = +1.80p / +$18.00 payout, Loss = -1.00p / -$10.00) and track running balance in `account_balance.txt`.
* **Signal Resolution:** Never resolve a trade until the exit candle is 100% closed (wait `exit_time + timeframe_delta` before fetching yfinance close price).
