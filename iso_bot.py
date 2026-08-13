import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from flask import Flask
from threading import Thread
from tradingview_ta import TA_Handler, Interval

# --- WEB SUNUCUSU (Render Port Uyarısı Almamak İçin) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "İso Bot & Aria Whisper (Multithread) Aktif!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- TELEGRAM VE PİYASA AYARLARI ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "BOT_TOKENINIZI_BURAYA_YAZIN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "CHAT_IDINIZI_BURAYA_YAZIN")

SYMBOL = "XAUUSD"
EXCHANGE = "OANDA"
TARGET_PIPS = 1.0  # +1$ Target

session = requests.Session()

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        session.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram Hatası: {e}")

# --- TÜRKİYE SAATİ FORMATLAMA (UTC+3) ---
def get_tr_time():
    utc_now = datetime.now(timezone.utc)
    tr_now = utc_now + timedelta(hours=3)
    return tr_now.strftime("%d.%m.%Y - %H:%M:%S")

# --- HESAPLAMA YARDIMCILARI ---
def calc_sma(series, length):
    return series.rolling(length).mean()

def calc_ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def calc_rsi(series, length):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_cci(high, low, close, length):
    tp = (high + low + close) / 3
    sma_tp = tp.rolling(length).mean()
    mad = tp.rolling(length).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - sma_tp) / (0.015 * mad)

def calc_macd(series, fast=12, slow=26, signal=9):
    fast_ema = calc_ema(series, fast)
    slow_ema = calc_ema(series, slow)
    macd = fast_ema - slow_ema
    signal_line = calc_ema(macd, signal)
    return macd, signal_line

# --- ARIA'NIN YÜKSELİŞ FİSILTISI ---
def calculate_aria_whisper(df):
    if df is None or len(df) < 205:
        return False

    close = df['close']
    open_p = df['open']
    high = df['high']
    low = df['low']
    volume = df['volume']

    sma200 = calc_sma(close, 200)
    vol_ma = calc_sma(volume, 20)
    rsi = calc_rsi(close, 14)
    macd_line, signal_line = calc_macd(close, 12, 26, 9)
    
    ema4 = calc_ema(close, 4)
    ema5 = calc_ema(close, 5)

    is_uptrend = close > sma200
    is_bullish_candle = close > open_p
    is_bearish_candle = close < open_p
    is_high_volume = volume > (vol_ma * 1.5)
    
    is_momentum_bullish = (rsi > 40) & (rsi < 68) & (macd_line > signal_line)
    ema_ribbon_filter = ema4 > ema5

    dist_from_ema4 = ((close - ema4) / ema4) * 100
    not_overextended = dist_from_ema4 < 1.5

    strong_buy = is_uptrend & (is_bullish_candle | (is_bearish_candle & is_high_volume & is_momentum_bullish))
    next_candle_up = close.shift(1) < close

    final_buy_signal = strong_buy & next_candle_up & ema_ribbon_filter & not_overextended
    return bool(final_buy_signal.iloc[-2])

# --- ISO BOT HESAPLAMASI ---
def calculate_iso_bot(df):
    if df is None or len(df) < 30:
        return False

    close = df['close']
    high = df['high']
    low = df['low']

    rsi8 = calc_rsi(close, length=8)
    if rsi8 is None:
        return False

    highest_rsi = rsi8.rolling(10).max()
    lowest_rsi = rsi8.rolling(10).min()
    stoch_raw = np.where(highest_rsi == lowest_rsi, 0.0, (rsi8 - lowest_rsi) / (highest_rsi - lowest_rsi))
    stoch_k = pd.Series(stoch_raw, index=df.index).rolling(3).mean() * 100

    rsi9 = calc_rsi(close, length=7)
    cci15 = calc_cci(high, low, close, length=15)
    cci20 = calc_cci(high, low, close, length=20)
    cci25 = calc_cci(high, low, close, length=25)

    ema1 = calc_ema(close, length=18)
    ema2 = calc_ema(ema1, length=18)
    ema3 = calc_ema(ema2, length=18)
    trix = 100 * (ema3 - ema3.shift(1)) / ema3.shift(1)

    highest_high = high.rolling(18).max()
    lowest_low = low.rolling(18).min()
    value_range = np.maximum(highest_high - lowest_low, 0.001)

    raw_val = 0.33 * 2 * ((close - lowest_low) / value_range - 0.5)
    val = np.zeros(len(df))
    fish = np.zeros(len(df))

    for i in range(1, len(df)):
        rv = raw_val.iloc[i] + 0.67 * val[i-1]
        val[i] = 0.999 if rv > 0.99 else (-0.999 if rv < -0.99 else rv)
        fish[i] = 0.5 * np.log((1 + val[i]) / max(1 - val[i], 0.001)) + 0.5 * fish[i-1]

    fish_series = pd.Series(fish, index=df.index)
    trig_series = fish_series.shift(1)

    stoch_over98 = (stoch_k.iloc[-10:] >= 98).any()
    fisher_cross_under = (fish_series.shift(1).iloc[-2] > trig_series.shift(1).iloc[-2]) and (fish_series.iloc[-2] < trig_series.iloc[-2])
    buy_fisher = fisher_cross_under and stoch_over98

    cond_stoch_rsi = (abs(stoch_k.iloc[-2] / 100) < 9) or (rsi9.iloc[-2] <= 45)
    buy15 = cond_stoch_rsi and (cci15.iloc[-3] < -90 and cci15.iloc[-2] >= -90)
    buy20 = cond_stoch_rsi and (cci20.iloc[-3] < -90 and cci20.iloc[-2] >= -90)
    buy25 = cond_stoch_rsi and (cci25.iloc[-3] < -90 and cci25.iloc[-2] >= -90)

    f_up = 1 if fish_series.iloc[-2] > fish_series.iloc[-3] else 0
    s_up = 1 if stoch_k.iloc[-2] > stoch_k.iloc[-3] else 0
    r_up = 1 if rsi9.iloc[-2] > rsi9.iloc[-3] else 0
    c15_up = 1 if cci15.iloc[-2] > cci15.iloc[-3] else 0
    c20_up = 1 if cci20.iloc[-2] > cci20.iloc[-3] else 0
    c25_up = 1 if cci25.iloc[-2] > cci25.iloc[-3] else 0

    up_count = f_up + s_up + r_up + c15_up + c20_up + c25_up
    trix_up = trix.iloc[-2] > trix.iloc[-3]

    buy_trend = (up_count >= 4) and trix_up
    any_buy = buy15 or buy20 or buy25 or buy_fisher or buy_trend

    return bool(any_buy)

def check_all_signals(df):
    iso_buy = calculate_iso_bot(df)
    aria_buy = calculate_aria_whisper(df)
    return iso_buy or aria_buy

# HAFIZA SÖZLÜKLERİ
last_signals = {}
active_targets = {}

# --- TV-TA İLE GÜVENLİ VERİ ÇEKME ---
def fetch_safe_df(tf_val):
    try:
        handler = TA_Handler(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            screener="forex",
            interval=tf_val
        )
        analysis = handler.get_analysis()
        # tradingview_ta'dan gelen son verileri df formatına dönüştürme
        # Not: Analiz göstergeleri üzerinden dataframe simülasyonu
        ind = analysis.indicators
        df = pd.DataFrame([{
            'open': ind.get('open', 0),
            'high': ind.get('high', 0),
            'low': ind.get('low', 0),
            'close': ind.get('close', 0),
            'volume': ind.get('volume', 0)
        }])
        return df, ind.get('close'), ind.get('high')
    except Exception as e:
        return None, None, None

# --- PARALEL PERİYOT TARAYICI ---
def monitor_timeframe(tf_name, tf_val):
    print(f"⚡ [{tf_name}] İşçisi Başlatıldı.")
    active_targets[tf_name] = []

    while True:
        try:
            handler = TA_Handler(
                symbol=SYMBOL,
                exchange=EXCHANGE,
                screener="forex",
                interval=tf_val
            )
            analysis = handler.get_analysis()
            ind = analysis.indicators

            close_p = ind.get("close")
            high_p = ind.get("high")

            # Basit Al Sinyal Mantığı
            rsi14 = ind.get("RSI")
            cci20 = ind.get("CCI20")
            sma200 = ind.get("SMA200")
            
            aria_buy = (close_p > sma200) and (rsi14 > 40 and rsi14 < 68) if (sma200 and rsi14) else False
            iso_buy = (cci20 < -90) if cci20 else False
            buy = aria_buy or iso_buy

            tr_tarih_saat = get_tr_time()

            # 1. HEDEF KONTROLÜ
            targets_to_remove = []
            for target_price in active_targets[tf_name]:
                if high_p >= target_price or close_p >= target_price:
                    target_msg = f"XAU USD LONG 100 PİP HEDEFTE✅\nOANDA:XAUUSD [{tf_name}], price = {target_price:.3f}\nTarih/Saat = {tr_tarih_saat}"
                    send_telegram(target_msg)
                    print(f"🎯 [{tf_name}] HEDEF YAKALANDI: {target_price} | Zaman: {tr_tarih_saat}")
                    targets_to_remove.append(target_price)

            for tp in targets_to_remove:
                active_targets[tf_name].remove(tp)

            # 2. SİNYAL KONTROLÜ
            if buy and not active_targets[tf_name]:
                target_price = close_p + TARGET_PIPS
                active_targets[tf_name].append(target_price)

                signal_msg = f"XAU USD LONG HEDEF 100 PİP🚨\nOANDA:XAUUSD [{tf_name}], price = {close_p:.3f}\nTarih/Saat = {tr_tarih_saat}"
                send_telegram(signal_msg)
                print(f"🚨 [{tf_name}] SİNYAL GÖNDERİLDİ! Fiyat: {close_p} | Zaman: {tr_tarih_saat}")

            # TradingView rate limit engeline takılmamak için bekletme
            time.sleep(12)

        except Exception as e:
            time.sleep(5)

def start_bot():
    print(">>> İSO BOT & ARIA MULTITHREAD BAŞLATILDI <<<")

    intervals = {
        "5m": Interval.INTERVAL_5_MINUTES,
        "15m": Interval.INTERVAL_15_MINUTES,
        "30m": Interval.INTERVAL_30_MINUTES,
        "1h": Interval.INTERVAL_1_HOUR,
        "2h": Interval.INTERVAL_2_HOURS,
        "4h": Interval.INTERVAL_4_HOURS
    }

    for tf_name, tf_val in intervals.items():
        t = Thread(target=monitor_timeframe, args=(tf_name, tf_val))
        t.daemon = True
        t.start()
        time.sleep(1)

    while True:
        time.sleep(10)

if __name__ == "__main__":
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    start_bot()
