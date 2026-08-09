import math
import os
import time
import numpy as np
import pandas as pd
import requests

# --- TELEGRAM VE BOTA ÖZEL BİLGİLER ---
TELEGRAM_BOT_TOKEN = "8818761631:AAF0hk73Omd3yZO6jE1BpzaJEaeDTxNpze8"
TELEGRAM_CHAT_ID = "-1004307934355"  # XAU SİNYAL Grubu ID'si

SYMBOL = "BTCUSDT"  # Takip edilecek parite (İstediğin coin ile değiştirebilirsin)
TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h"]  # Taranacak zaman dilimleri

# Her zaman dilimi için son işlenen kapalı mumun zaman damgası
last_processed_timestamps = {tf: None for tf in TIMEFRAMES}


def send_telegram(message):
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {
      "chat_id": TELEGRAM_CHAT_ID,
      "text": message,
      "parse_mode": "Markdown",
  }
  try:
    requests.post(url, json=payload, timeout=10)
  except Exception as e:
    print(f"Telegram gönderme hatası: {e}")


def get_klines(symbol=SYMBOL, interval="1h", limit=200):
  url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
  res = requests.get(url, timeout=10)
  data = res.json()

  df = pd.DataFrame(
      data,
      columns=[
          "timestamp",
          "open",
          "high",
          "low",
          "close",
          "volume",
          "close_time",
          "qav",
          "num_trades",
          "taker_base_vol",
          "taker_quote_vol",
          "ignore",
      ],
  )
  df["open"] = df["open"].astype(float)
  df["high"] = df["high"].astype(float)
  df["low"] = df["low"].astype(float)
  df["close"] = df["close"].astype(float)
  return df


# --- İSO BOT TEKNİK HESAPLAMALARI ---
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
  trix = 100 * (ema3 - ema3.shift(1)) / ema3.shift(1)
  return trix


def analyze_iso_bot(df):
  n = len(df)

  # 1. RSI ve Stokastik
  df["rsi8"] = calculate_rsi(df["close"], 8)

  stoch_raw = np.zeros(n)
  for i in range(n):
    if i < 10:
      continue
    sub = df["rsi8"].iloc[i - 9 : i + 1]
    hi, lo = sub.max(), sub.min()
    stoch_raw[i] = 0.0 if hi == lo else (df["rsi8"].iloc[i] - lo) / (hi - lo)

  df["stochRaw"] = stoch_raw
  df["stochK"] = pd.Series(stoch_raw).rolling(window=3).mean() * 100
  df["rsi9"] = calculate_rsi(df["close"], 7)

  # 2. CCI Değerleri
  df["cci15"] = calculate_cci(df, 15)
  df["cci20"] = calculate_cci(df, 20)
  df["cci25"] = calculate_cci(df, 25)

  # 3. TRIX
  df["trix"] = calculate_trix(df["close"], 18)

  # 4. Fisher İndikatörü ve Hafıza Döngüsü
  fisher_arr = np.zeros(n)
  trigger_arr = np.zeros(n)
  value_var = 0.0
  fisher_var = 0.0

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

  df["fisher"] = fisher_arr
  df["trigger"] = trigger_arr
  df["buySignalFisher"] = buySignalFisher

  # 5. Sinyaller
  nearZeroTol = 9
  condStochOrRsi = (np.abs(df["stochK"] / 100) < nearZeroTol) | (
      df["rsi9"] <= 45
  )

  df["buySignal15"] = (
      condStochOrRsi & (df["cci15"].shift(1) <= -90) & (df["cci15"] > -90)
  )
  df["buySignal20"] = (
      condStochOrRsi & (df["cci20"].shift(1) <= -90) & (df["cci20"] > -90)
  )
  df["buySignal25"] = (
      condStochOrRsi & (df["cci25"].shift(1) <= -90) & (df["cci25"] > -90)
  )

  # 6. Trend Sinyali
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


# --- KONTROL MOTORU (MUM KAPANIS TAKIBI) ---
def check_timeframe(tf):
  global last_processed_timestamps

  try:
    df = get_klines(symbol=SYMBOL, interval=tf, limit=200)
    df = analyze_iso_bot(df)

    # Kapanmış olan son mum (iloc[-2])
    closed_candle = df.iloc[-2]
    candle_time = closed_candle["timestamp"]

    if last_processed_timestamps[tf] == candle_time:
      return

    last_processed_timestamps[tf] = candle_time
    close_price = closed_candle["close"]

    signals = []
    if closed_candle["buySignal15"]:
      signals.append("AL (CCI 15)")
    if closed_candle["buySignal20"]:
      signals.append("AL (CCI 20)")
    if closed_candle["buySignal25"]:
      signals.append("AL (CCI 25)")
    if closed_candle["buySignalFisher"]:
      signals.append("AL (Fisher)")
    if closed_candle["buySignalTrend"]:
      signals.append("AL (Trend)")

    if signals:
      signal_text = ", ".join(signals)
      msg = (
          f"🚨 *İso Bot Sinyal Alarmı!*\n\n"
          f"📊 *Parite:* {SYMBOL}\n"
          f"⏱ *Zaman Dilimi:* `{tf}` (Mum Kapanışı)\n"
          f"💰 *Kapanış Fiyatı:* {close_price}\n"
          f"⚡ *Sinyal:* `{signal_text}`"
      )
      send_telegram(msg)
      print(
          f"[{time.strftime('%H:%M:%S')}] [{tf}] Gruba sinyal fırlatıldı:"
          f" {signal_text}"
      )
  except Exception as e:
      print(f"[{tf}] Hata oluştu: {e}")


def run_bot():
  for tf in TIMEFRAMES:
    check_timeframe(tf)


if __name__ == "__main__":
  send_telegram(
      f"🤖 *Çoklu Zaman Dilimli İso Bot Aktif!*\n"
      f"📊 *Parite:* {SYMBOL}\n"
      f"⏱ *Dilimler:* 5m, 15m, 30m, 1h, 4h\n"
      f"✅ *Kurulum:* Mum kapanışı takibi aktif."
  )
  while True:
    try:
      run_bot()
    except Exception as e:
      print(f"Ana döngü hatası: {e}")
    time.sleep(15)
