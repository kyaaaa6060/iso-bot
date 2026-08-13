import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from flask import Flask
from threading import Thread
from tradingview_ta import TA_Handler, Interval

# --- WEB SUNUCUSU (Render Kapanmasın Diye) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "İso Bot & Aria (Tam Bağımsız Stratejiler) Fırlatıcı Çalışıyor!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- TELEGRAM VE PİYASA AYARLARI ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

SYMBOL = "XAUUSD"
EXCHANGE = "OANDA"
TARGET_PIPS = 1.0  # 100 Pip (+1.0$)

session = requests.Session()

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        response = session.post(url, json=payload, timeout=5)
        print(f"📩 Telegram Yanıtı [{response.status_code}]: {response.text}")
    except Exception as e:
        print(f"❌ Telegram Hatası: {e}")

def get_tr_time():
    utc_now = datetime.now(timezone.utc)
    tr_now = utc_now + timedelta(hours=3)
    return tr_now.strftime("%d.%m.%Y - %H:%M:%S")

# --- SENİN ÖZEL İNDİKATÖR HESAPLAMALARIN ---
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
def calculate_aria_whisper(df, sma_period=200, atr_period=14, vol_ma_period=20, hacim_esik=1.5, 
                           rsi_len=14, rsi_oversold=40, rsi_overbought=68, 
                           macd_fast=12, macd_slow=26, macd_signal=9, 
                           ema4_len=4, ema5_len=5, use_dist_filter=True, max_dist_percent=1.5):
    if df is None or len(df) < sma_period + 5:
        return False

    close = df['close']
    open_p = df['open']
    volume = df['volume']

    sma200 = calc_sma(close, sma_period)
    vol_ma = calc_sma(volume, vol_ma_period)
    rsi = calc_rsi(close, rsi_len)
    macd_line, signal_line = calc_macd(close, macd_fast, macd_slow, macd_signal)
    
    ema4 = calc_ema(close, ema4_len)
    ema5 = calc_ema(close, ema5_len)

    is_uptrend = close > sma200
    is_bullish_candle = close > open_p
    is_bearish_candle = close < open_p
    is_high_volume = volume > (vol_ma * hacim_esik)
    
    is_momentum_bullish = (rsi > rsi_oversold) & (rsi < rsi_overbought) & (macd_line > signal_line)
    ema_ribbon_filter = ema4 > ema5

    dist_from_ema4 = ((close - ema4) / ema4) * 100
    not_overextended = (~use_dist_filter) | (dist_from_ema4 < max_dist_percent)

    strong_buy = is_uptrend & (is_bullish_candle | (is_bearish_candle & is_high_volume & is_momentum_bullish))
    next_candle_up = close.shift(1) < close

    final_buy_signal = strong_buy & next_candle_up & ema_ribbon_filter & not_overextended
    return final_buy_signal.iloc[-2]

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

    stoch_over98 = (stoch_k.iloc[-11:-1] >= 98).any()
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
    return buy15 or buy20 or buy25 or buy_fisher or buy_trend

# STRATEJİLER İÇİN AYRI HAFIZA VE HEDEF SÖZLÜKLERİ
last_signals_iso = {}
active_targets_iso = {}

last_signals_aria = {}
active_targets_aria = {}

# --- PARALEL PERİYOT TARAYICI ---
def monitor_timeframe(tf_name, tf_val):
    print(f"⚡ [{tf_name}] Bağımsız İşçisi Çalıştırıldı.")
    
    handler = TA_Handler(
        symbol=SYMBOL,
        exchange=EXCHANGE,
        screener="forex",
        interval=tf_val
    )

    active_targets_iso[tf_name] = []
    active_targets_aria[tf_name] = []

    while True:
        try:
            analysis = handler.get_analysis()
            ind = analysis.indicators

            close_val = ind.get("close")
            high_val = ind.get("high")
            low_val = ind.get("low")
            open_val = ind.get("open")
            vol_val = ind.get("volume", 100)

            data = {
                'open': [open_val]*220,
                'high': [high_val]*220,
                'low': [low_val]*220,
                'close': [close_val]*220,
                'volume': [vol_val]*220
            }
            df = pd.DataFrame(data)
            tr_tarih_saat = get_tr_time()

            # --- STRATEJİ 1: ISO BOT (BAĞIMSIZ) ---
            iso_buy = calculate_iso_bot(df)
            
            # Iso Hedef Kontrolü
            targets_to_remove_iso = []
            for target_price in active_targets_iso[tf_name]:
                if high_val >= target_price or close_val >= target_price:
                    msg = (
                        f"🎯 XAU USD LONG 100 PİP HEDEFTE✅ [ISO BOT]\n"
                        f"OANDA:XAUUSD [{tf_name}], price = {target_price:.3f}\n"
                        f"Tarih/Saat = {tr_tarih_saat}"
                    )
                    send_telegram(msg)
                    targets_to_remove_iso.append(target_price)
            for tp in targets_to_remove_iso:
                active_targets_iso[tf_name].remove(tp)

            # Iso Sinyal Kontrolü
            if iso_buy and not last_signals_iso.get(tf_name, False):
                last_signals_iso[tf_name] = True
                target_price = close_val + TARGET_PIPS
                active_targets_iso[tf_name].append(target_price)
                msg = (
                    f"🚨 XAU USD LONG HEDEF 100 PİP [ISO BOT]\n"
                    f"OANDA:XAUUSD [{tf_name}], price = {close_val:.3f}\n"
                    f"Tarih/Saat = {tr_tarih_saat}"
                )
                send_telegram(msg)
            elif not iso_buy:
                last_signals_iso[tf_name] = False


            # --- STRATEJİ 2: ARIA WHISPER (BAĞIMSIZ) ---
            aria_buy = calculate_aria_whisper(df)
            
            # Aria Hedef Kontrolü
            targets_to_remove_aria = []
            for target_price in active_targets_aria[tf_name]:
                if high_val >= target_price or close_val >= target_price:
                    msg = (
                        f"🎯 XAU USD LONG 100 PİP HEDEFTE✅ [ARIA WHISPER]\n"
                        f"OANDA:XAUUSD [{tf_name}], price = {target_price:.3f}\n"
                        f"Tarih/Saat = {tr_tarih_saat}"
                    )
                    send_telegram(msg)
                    targets_to_remove_aria.append(target_price)
            for tp in targets_to_remove_aria:
                active_targets_aria[tf_name].remove(tp)

            # Aria Sinyal Kontrolü
            if aria_buy and not last_signals_aria.get(tf_name, False):
                last_signals_aria[tf_name] = True
                target_price = close_val + TARGET_PIPS
                active_targets_aria[tf_name].append(target_price)
                msg = (
                    f"🚨 XAU USD LONG HEDEF 100 PİP [ARIA WHISPER]\n"
                    f"OANDA:XAUUSD [{tf_name}], price = {close_val:.3f}\n"
                    f"Tarih/Saat = {tr_tarih_saat}"
                )
                send_telegram(msg)
            elif not aria_buy:
                last_signals_aria[tf_name] = False

            time.sleep(1.5)

        except Exception as e:
            time.sleep(2)

def start_bot():
    print(">>> İSO BOT & ARIA İKİ BAĞIMSIZ STRATEJİ İLE BAŞLATILDI <<<")
    
    tr_start_time = get_tr_time()
    send_telegram(f"🤖 İso Bot & Aria (İki Bağımsız Strateji) Aktif 🔥\nTarih/Saat = {tr_start_time}")

    intervals = {
        "5m": Interval.INTERVAL_5_MINUTES,
        "15m": Interval.INTERVAL_15_MINUTES,
        "30m": Interval.INTERVAL_30_MINUTES,
        "1h": Interval.INTERVAL_1_HOUR,
        "2h": Interval.INTERVAL_2_HOURS,
        "3h": "3h",
        "4h": Interval.INTERVAL_4_HOURS
    }

    for tf_name, tf_val in intervals.items():
        t = Thread(target=monitor_timeframe, args=(tf_name, tf_val))
        t.daemon = True
        t.start()
        time.sleep(0.3)

    while True:
        time.sleep(10)

if __name__ == "__main__":
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    start_bot()
