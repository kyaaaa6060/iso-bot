import math
import os
import threading
import time

from flask import Flask
import numpy as np
import pandas as pd
import requests
import yfinance as yf

# --- TELEGRAM BİLGİLERİ ---
TELEGRAM_BOT_TOKEN = "8818761631:AAF0hk73Omd3yZO6jE1BpzaJEaeDTxNpze8"
TELEGRAM_CHAT_ID = "-1004307934355"  # XAU SİNYAL Grubu

TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h"]

last_processed_timestamps = {tf: None for tf in TIMEFRAMES}
active_trades = {tf: [] for tf in TIMEFRAMES}

# --- FLASK SUNUCUSU (RENDER İÇİN) ---
app = Flask("")


@app.route("/")
def home():
  return "XAUUSD İso Bot Aktif!"


def run_web():
  port = int(os.environ.get("PORT", 8080))
  app.run(host="0.0.0.0", port=port)


def send_telegram(message):
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
  try:
    requests.post(url, json=payload, timeout=10)
  except Exception as e:
    print(f"Telegram gönderme hatası: {e}")


# --- VERİ ÇEKME ---
def get_klines(interval="1h"):
  ticker = yf.Ticker("XAUUSD=X")

  if interval == "4h":
    df = ticker.history(period="14d", interval="1h")
    df = (
        df.resample("4h")
        .agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        })
        .dropna()
        .reset_index()
    )
  else:
    tf_map = {"5m": "5m", "15m": "15m", "30m": "30m", "1h": "60m"}
    yf_tf = tf_map.get(interval, "60m")
    df = ticker.history(period="7d", interval=yf_tf).reset_index()

  df.columns = [c.lower() for c in df.columns]

  if "datetime" in df.columns:
    df["timestamp"] = df["datetime"]
  elif "date" in df.columns:
    df["timestamp"] = df["date"]

  return df


# --- İNDİKATÖR HESAPLAMALARI ---
def rma(series, length):
  return series.ewm(alpha=1 / length, adjust=False).mean()


def calculate_rsi(series, length):
  delta = series.diff()
  gain = delta.where(delta > 0, 0.0)
  loss = -delta.where(delta < 0, 0.0)
  avg_gain = rma(gain, length)
  avg_loss = rma(loss, length)
  rs = avg_gain / avg_loss
  return 100 - (100 / (1 + rs))


def calculate_cci(df, length):
  tp = (df["high"] + df["low"] + df["close"]) / 3
  sma = tp.rolling(window=length).mean()
  mad = (tp - sma).abs().rolling(window=length).mean()
  return (tp - sma) / (0.015 * mad)


def calculate_trix(series, length=18):
  ema1 = series.ewm(span=length, adjust=False).mean()
  ema2 = ema1.ewm(span=length, adjust=False).mean()
  ema3 = ema2.ewm(span=length, adjust=False).mean()
  return 100 * (ema3 - ema3.shift(1)) / ema3.shift(1)


def analyze_iso_bot(df):
  n = len(df)
  if n < 20:
    return df

  df["rsi8"] = calculate_rsi(df["close"], 8)

  stoch_raw = np.zeros(n)
  for i in range(n):
    if i < 10:
      continue
    sub = df["rsi8"].iloc[i - 9 : i + 1]
    hi, lo = sub.max(), sub.min()
    stoch_raw[i] = 0.0 if hi == lo else (df["rsi8"].iloc[i] - lo) / (hi - lo)

  df["stochK"] = pd.Series(stoch_raw).rolling(window=3).mean() * 100
  df["rsi9"] = calculate_rsi(df["close"], 7)

  df["cci15"] = calculate_cci(df, 15)
  df["cci20"] = calculate_cci(df, 20)
  df["cci25"] = calculate_cci(df, 25)
  df["trix"] = calculate_trix(df["close"], 18)

  fisher_arr, trigger_arr = np.zeros(n), np.zeros(n)
  value_var, fisher_var = 0.0, 0.0
  stochK_Over98 = False
  buySignalFisher = np.zeros(n, dtype=bool)

  for i in range(n):
    if i < 18:
      continue
    sub_high = df["high"].iloc[i - 17 : i + 1].max()
    sub_low = df["low"].iloc[i - 17 : i + 1].min()
    v_range = max(sub_high - sub_low, 0.001)

    raw_val = (
        0.33 * 2 * ((df["close"].iloc[i] - sub_low) / v_range - 0.5)
        + 0.67 * value_var
    )
    value_var = 0.999 if raw_val > 0.99 else (-0.999 if raw_val < -0.99 else raw_val)

    fisher_var = (
        0.5 * math.log((1 + value_var) / max(1 - value_var, 0.001))
        + 0.5 * fisher_var
    )
    fisher_arr[i] = fisher_var
    trigger_arr[i] = fisher_arr[i - 1] if i > 0 else 0.0

    stk = df["stochK"].iloc[i]
    if not np.isnan(stk) and stk >= 98:
      stochK_Over98 = True

    fisher_cross_under = (fisher_arr[i - 1] > trigger_arr[i - 1]) and (
        fisher_arr[i] < trigger_arr[i]
    )
    if stochK_Over98 and fisher_cross_under:
      buySignalFisher[i] = True
      stochK_Over98 = False

  df["fisher"], df["trigger"] = fisher_arr, trigger_arr
  df["buySignalFisher"] = buySignalFisher

  condStochOrRsi = (np.abs(df["stochK"] / 100) < 9) | (df["rsi9"] <= 45)
  df["buySignal15"] = (
      condStochOrRsi & (df["cci15"].shift(1) <= -90) & (df["cci15"] > -90)
  )
  df["buySignal20"] = (
      condStochOrRsi & (df["cci20"].shift(1) <= -90) & (df["cci20"] > -90)
  )
  df["buySignal25"] = (
      condStochOrRsi & (df["cci25"].shift(1) <= -90) & (df["cci25"] > -90)
  )

  fisherUp = (df["fisher"] > df["fisher"].shift(1)).astype(int)
  stochKUp = (df["stochK"] > df["stochK"].shift(1)).astype(int)
  rsiUp = (df["rsi9"] > df["rsi9"].shift(1)).astype(int)
  cci15Up = (df["cci15"] > df["cci15"].shift(1)).astype(int)
  cci20Up = (df["cci20"] > df["cci20"].shift(1)).astype(int)
  cci25Up = (df["cci25"] > df["cci25"].shift(1)).astype(int)

  upCount = fisherUp + stochKUp + rsiUp + cci15Up + cci20Up + cci25Up
  trixUp = df["trix"] > df["trix"].shift(1)
  df["buySignalTrend"] = (upCount >= 4) & (upCount.shift(1) < 4) & trixUp

  return df


# --- KONTROL VE BİLDİRİM MOTORU ---
def check_timeframe(tf):
  global last_processed_timestamps, active_trades

  try:
    df = get_klines(interval=tf)
    df = analyze_iso_bot(df)

    latest_candle = df.iloc[-1]
    current_high = latest_candle["high"]

    # 1. HEDEF KONTROLÜ (Aynı mumda bakılmaz, sonraki mumlarda bakılır)
    remaining_trades = []
    for trade in active_trades[tf]:
      if (
          latest_candle["timestamp"] > trade["timestamp"]
          and current_high >= trade["target"]
      ):
        dt_str = pd.to_datetime(latest_candle["timestamp"]).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        msg = (
            f"XAU USD LONG 100 PİP HEDEFTE✅\n"
            f"OANDA:XAUUSD, price = {trade['target']:.3f}\n"
            f"DateTime = {dt_str}"
        )
        send_telegram(msg)
      else:
        remaining_trades.append(trade)

    active_trades[tf] = remaining_trades

    # 2. SİNYAL KONTROLÜ
    closed_candle = df.iloc[-2]
    candle_time = closed_candle["timestamp"]

    if last_processed_timestamps[tf] == candle_time:
      return

    last_processed_timestamps[tf] = candle_time
    close_price = float(closed_candle["close"])
    target_price = close_price + 1.0  # 100 Pip = 1.0 Dolar

    has_signal = (
        closed_candle["buySignal15"]
        or closed_candle["buySignal20"]
        or closed_candle["buySignal25"]
        or closed_candle["buySignalFisher"]
        or closed_candle["buySignalTrend"]
    )

    if has_signal:
      dt_str = pd.to_datetime(candle_time).strftime("%Y-%m-%dT%H:%M:%SZ")
      msg = (
          f"XAU USD LONG HEDEF 100 PİP🚨\n"
          f"OANDA:XAUUSD, price = {close_price:.3f}\n"
          f"DateTime = {dt_str}"
      )
      send_telegram(msg)

      active_trades[tf].append({
          "entry": close_price,
          "target": target_price,
          "timestamp": candle_time,
      })

  except Exception as e:
    print(f"[{tf}] Hata: {e}")


def run_bot():
  for tf in TIMEFRAMES:
    check_timeframe(tf)


if __name__ == "__main__":
  threading.Thread(target=run_web, daemon=True).start()

  send_telegram(
      "🤖 XAUUSD İso Bot Aktif!\nTakip Dilimleri: 5m, 15m, 30m, 1h, 4h\nHedef:"
      " 100 Pip (+1.0$)"
  )

  while True:
    try:
      run_bot()
    except Exception as e:
      print(f"Ana döngü hatası: {e}")
    time.sleep(20)
