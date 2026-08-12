import os
import time
import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from flask import Flask
from threading import Thread

# TvDatafeed gereksiz uyarı ve loglarını tamamen gizle (Log ekranı temiz kalır)
logging.getLogger("tvDatafeed").setLevel(logging.CRITICAL)

# --- TVDATAFEED IMPORT ---
try:
    from tvDatafeed import TvDatafeed as Tvdatafeed, Interval
except ImportError:
    try:
        from tvDatafeed import Tvdatafeed, Interval
    except ImportError:
        from tvdatafeed import Tvdatafeed, Interval

# --- WEB SUNUCUSU ---
app = Flask(__name__)

@app.route('/')
def home():
    return "İso Bot Saniye Takipli & Kesintisiz Modda Aktif!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- AYARLAR ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

SYMBOL = "XAUUSD"
EXCHANGE = "OANDA"
TARGET_PIPS = 1.0  

# Hızlı Telegram Gönderici (Requests Session ile Bağlantı Hızlandırma)
session = requests.Session()

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        session.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram Hatası: {e}")

# --- TEKNİK İNDİKATÖR HESAPLAMALARI ---
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

def calc_atr(high, low, close, length):
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, min_periods=length, adjust=False).mean()

def calc_macd(series, fast=12, slow=26, signal=9):
    fast_ema = calc_ema(series, fast)
    slow_ema = calc_ema(series, slow)
    macd = fast_ema - slow_ema
    signal_line = calc_ema(macd, signal)
    return macd, signal_line

# --- ARIA'NIN YÜKSELİŞ FİSILTISI (TEPE FİLTRELİ) ---
def calculate_aria_whisper(df, sma_period=200, atr_period=14, vol_ma_period=20, hacim_esik=1.5, 
                           rsi_len=14, rsi_oversold=40, rsi_overbought=68, 
                           macd_fast=12, macd_slow=26, macd_signal=9, 
                           ema4_len=4, ema5_len=5, use_dist_filter=True, max_dist_percent=1.5):
    if df is None or len(df) < sma_period + 5:
        return False, ""

    close = df['close']
    open_p = df['open']
    high = df['high']
    low = df['low']
    volume = df['volume']

    # İndikatör Hesaplamaları
    sma200 = calc_sma(close, sma_period)
    atr = calc_atr(high, low, close, atr_period)
    vol_ma = calc_sma(volume, vol_ma_period)
    rsi = calc_rsi(close, rsi_len)
    macd_line, signal_line = calc_macd(close, macd_fast, macd_slow, macd_signal)
    
    ma4 = calc_ema(close, ema4_len)
    ma5 = calc_ema(close, ema5_len)

    # Mantıksal Koşullar
    is_uptrend = close > sma200
    is_bullish_candle = close > open_p
    is_bearish_candle = close < open_p
    is_high_volatility = (high - low) > atr
    is_high_volume = volume > (vol_ma * hacim_esik)
    
    is_momentum_bullish = (rsi > rsi_oversold) & (rsi < rsi_overbought) & (macd_line > signal_line)
    ma_filter = ma4 > ma5

    dist_from_ma4 = ((close - ma4) / ma4) * 100
    not_overextended = (~use_dist_filter) | (dist_from_ma4 < max_dist_percent)

    strong_buy = is_uptrend & (is_bullish_candle | (is_bearish_candle & is_high_volume & is_momentum_bullish))
    next_candle_up = close.shift(1) < close

    final_buy_signal = strong_buy & next_candle_up & ma_filter & not_overextended

    # Kapanmış son mum kontrolü (iloc[-2])
    is_aria_buy = final_buy_signal.iloc[-2]

    return is_aria_buy, "ARIA_WHISPER" if is_aria_buy else ""

# --- ESKİ ISO BOT HESAPLAMASI ---
def calculate_iso_bot(df):
    if df is None or len(df) < 30:
        return False, ""

    close = df['close']
    high = df['high']
    low = df['low']

    rsi8 = calc_rsi(close, length=8)
    if rsi8 is None:
        return False, ""

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
    sig_type = "FISHER" if buy_fisher else ("TREND" if buy_trend else ("CCI15" if buy15 else ("CCI20" if buy20 else ("CCI25" if buy25 else ""))))

    return any_buy, sig_type

# BİRLEŞTİRİLMİŞ SİNYAL KONTROLÜ
def check_all_signals(df):
    iso_buy, iso_sig = calculate_iso_bot(df)
    aria_buy, aria_sig = calculate_aria_whisper(df)
    
    if aria_buy:
        return True, aria_sig
    elif iso_buy:
        return True, iso_sig
    
    return False, ""

# HAFIZA SÖZLÜKLERİ
last_signals = {}
active_targets = {}

def fetch_safe(tv, tf_val):
    try:
        # SMA200 hesabı için en az 210-220 mum veri çekilmesi gerekir.
        return tv.get_hist(symbol=SYMBOL, exchange=EXCHANGE, interval=tf_val, n_bars=220)
    except Exception:
        return None

def start_bot():
    print(">>> İSO & ARIA BİRLEŞİK BOT SANİYE TAKİPLİ & STABİL MODDA BAŞLATILDI <<<")
    tv = Tvdatafeed()

    intervals = {
        "5m": Interval.in_5_minute,
        "15m": Interval.in_15_minute,
        "30m": Interval.in_30_minute,
        "1h": Interval.in_1_hour,
        "2h": Interval.in_2_hour,
        "4h": Interval.in_4_hour
    }

    while True:
        try:
            for tf_name, tf_val in intervals.items():
                df = fetch_safe(tv, tf_val)
                
                # Bağlantı koparsa oturumu yenile
                if df is None or df.empty:
                    tv = Tvdatafeed()
                    time.sleep(2)
                    df = fetch_safe(tv, tf_val)

                if df is not None and not df.empty:
                    buy, sig_type = check_all_signals(df)
                    last_bar_time = df.index[-2]
                    last_price = df['close'].iloc[-2]
                    current_high = df['high'].iloc[-1]   
                    current_close = df['close'].iloc[-1] 
                    formatted_time = last_bar_time.strftime('%Y-%m-%dT%H:%M:%SZ')

                    # 1. HEDEF KONTROLÜ
                    if tf_name in active_targets:
                        target_price = active_targets[tf_name]
                        if current_high >= target_price or current_close >= target_price:
                            send_time = datetime.now().strftime('%H:%M:%S')
                            target_msg = f"XAU USD LONG 100 PİP HEDEFTE✅\nOANDA:XAUUSD, price = {target_price:.3f}\nGönderim Zamanı = {send_time}\nDateTime = {formatted_time}"
                            send_telegram(target_msg)
                            print(f"🎯 [{tf_name}] HEDEF YAKALANDI: {target_price} | Zaman: {send_time}")
                            del active_targets[tf_name]

                    # 2. SİNYAL KONTROLÜ (HEDEF KİLİTLİ)
                    key = f"{tf_name}_{str(last_bar_time)}"
                    if buy and last_signals.get(tf_name) != key and tf_name not in active_targets:
                        last_signals[tf_name] = key
                        target_price = last_price + TARGET_PIPS
                        active_targets[tf_name] = target_price

                        send_time = datetime.now().strftime('%H:%M:%S')
                        signal_msg = f"XAU USD LONG HEDEF 100 PİP🚨 [{sig_type}]\nOANDA:XAUUSD, price = {last_price:.3f}\nGönderim Zamanı = {send_time}\nDateTime = {formatted_time}"
                        send_telegram(signal_msg)
                        print(f"🚨 [{tf_name}] SİNYAL GÖNDERİLDİ! Tip: {sig_type} | Fiyat: {last_price} | Zaman: {send_time}")
                    elif not buy:
                        last_signals[tf_name] = key

                time.sleep(1.0) # IP engeline takılmamak için zaman dilimleri arası es verme

            time.sleep(3.0) # Tur bitimindeki genel bekleme

        except Exception as e:
            tv = Tvdatafeed()
            time.sleep(5)

if __name__ == "__main__":
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    start_bot()
