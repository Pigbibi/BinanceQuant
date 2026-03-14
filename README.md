# BinanceQuant

Automated crypto quant for Binance spot: BTC DCA core plus altcoin trend rotation. Uses valuation (AHR999, Z-Score) and trend gates (MA200, slope). Compatible with Binance flexible earn (auto redeem/subscribe), USDT buffer, BNB fuel, Telegram alerts, and Firestore state.

**Trend universe source:** Prefer upstream published pool (e.g. CryptoLeaderRotation) via Firestore or `live_pool_legacy.json`. Fallback: built-in static pool.

## Layout

- **main.py** — Live script (run hourly).
- **backtest.py** — Research/backtest (pool selection, ranking, risk).
- **requirements.txt** — Python deps.

## Strategy Overview

- **BTC core:** Valuation-based DCA (AHR999) and scaled take-profit (Z-Score vs dynamic threshold). Target weight grows with equity.
- **Trend layer:** Monthly refreshed pool (upstream or internal stable-quality rank), then Top 2 by relative-BTC strength, inverse-vol weighted. Only active when BTC gate is on.

Runs hourly; signals are daily trend and risk, not high-frequency.

## BTC Core

**Indicators:** MA200, MA200 slope, AHR999, Z-Score, dynamic Z-Score sell threshold.

**Logic:** Stronger DCA when AHR999 low; normal when neutral; scaled sells when Z-Score above threshold. Higher Z-Score → larger sell fraction.

**Target weight:** `btc_target_ratio = 0.14 + 0.16 * ln(1 + total_equity / 10000)`, capped. Larger equity → more BTC, less trend.

**DCA size:** Daily base order scales with total equity.

## Trend Rotation

**Universe:** From upstream (Firestore or `live_pool_legacy.json`) or static fallback. Priority: Firestore → `TREND_POOL_FILE` → default paths → static pool.

**Monthly pool:** Upstream publishes a 5-coin production pool; this repo consumes it. “Stable quality” favours: stable trend structure, relative BTC strength, liquidity, low liquidity variance, trend persistence.

**Factors:** SMA20/60/200, 20/60/120d returns, 20d vol, ATR14, 30/90/180d avg quote volume, trend persistence, relative BTC strength, risk-adjusted momentum.

**Holdings:** Top 2 from pool by relative-BTC score; inverse-vol weights.

**Entry:** BTC gate on; price above SMA20/60/200; positive relative-BTC score; positive absolute momentum.

**Exit:** Below SMA60; ATR trailing stop; rotated out of Top 2.

## Risk

- **BTC gate:** Trend layer only when `BTC price > MA200` and `MA200 slope > 0`.
- **Circuit breaker:** If trend-layer daily PnL ≤ threshold, flatten trend book; BTC core unchanged.
- **BNB:** Auto top-up for fees; not in trend rotation.

## Earn Compatibility

- Check spot before orders; redeem from flexible earn if needed.
- Maintain USDT spot buffer (subscribe excess, redeem shortfall).

## State (Firestore)

- Trend positions, high-water prices, circuit state, DCA last buy/sell date, monthly pool id, pool symbols. Retired symbols (dropped from pool but still held) tracked until closed.

## Upstream Pool

**Default:** CryptoLeaderRotation monthly output.

1. Firestore `strategy` / `CRYPTO_LEADER_ROTATION_LIVE_POOL` (override: `TREND_POOL_FIRESTORE_COLLECTION`, `TREND_POOL_FIRESTORE_DOCUMENT`).
2. Local `live_pool_legacy.json` (override: `TREND_POOL_FILE`).
3. Static `TREND_UNIVERSE`.

**Format (`live_pool_legacy.json`):**

```json
{
  "as_of_date": "2026-03-13",
  "pool_size": 5,
  "symbols": {
    "TRXUSDT": {"base_asset": "TRX"},
    "ETHUSDT": {"base_asset": "ETH"}
  }
}
```

**Runtime:** Active pool drives new buys; retired symbols stay in state until sold. On pool load failure, fallback to static pool.

## Environment

Required:

| Variable | Description |
|----------|-------------|
| `BINANCE_API_KEY` | Binance API key |
| `BINANCE_API_SECRET` | Binance API secret |
| `TG_TOKEN` | Telegram bot token |
| `TG_CHAT_ID` | Telegram chat ID for alerts |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to GCP service account JSON (or use `GCP_SA_KEY` and write to `gcp-key.json` before run) |

Optional:

| Variable | Description |
|----------|-------------|
| `BTC_STATUS_REPORT_INTERVAL_HOURS` | Interval for BTC status report (default 24) |
| `TREND_POOL_FILE` | Path to `live_pool_legacy.json` |
| `TREND_POOL_FIRESTORE_COLLECTION` | Firestore collection for live pool (default `strategy`) |
| `TREND_POOL_FIRESTORE_DOCUMENT` | Firestore document for live pool (default `CRYPTO_LEADER_ROTATION_LIVE_POOL`) |

## Quick deploy

1. **Python 3.9+**, create venv and install deps:

```bash
cd /path/to/BinanceQuant
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

2. **Set environment variables** (example; use your own values):

```bash
export BINANCE_API_KEY="your_binance_api_key"
export BINANCE_API_SECRET="your_binance_api_secret"
export TG_TOKEN="your_telegram_bot_token"
export TG_CHAT_ID="your_telegram_chat_id"
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your-gcp-sa.json"
# Optional: upstream trend pool
export TREND_POOL_FILE="/path/to/live_pool_legacy.json"
# Optional: BTC status report interval (hours)
export BTC_STATUS_REPORT_INTERVAL_HOURS=24
```

3. **Run once:**

```bash
python3 main.py
```

4. **Schedule hourly** (cron):

```cron
0 * * * * cd /path/to/BinanceQuant && /path/to/BinanceQuant/.venv/bin/python main.py >> /path/to/BinanceQuant/run.log 2>&1
```

## Backtest

```bash
python3 backtest.py
```

Used to compare pool/ranking variants and event-window behaviour.

## Telegram

Alerts: trend buys/sells, BTC DCA, earn redeems, circuit breaker, errors. Optional periodic BTC status (AHR999, Z-Score, gate, trend PnL). Default once per day at UTC 00:00; set `BTC_STATUS_REPORT_INTERVAL_HOURS` to change.
