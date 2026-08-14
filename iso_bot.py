import os
import time
import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from flask import Flask
from threading import Thread

# TvDatafeed gereksiz uyarı ve loglarını tamamen gizle
logging.getLogger("tvDatafeed").setLevel(logging.CRITICAL)

# --- TVDATAFEED IMPORT ---
try:
    from tvDatafeed import TvDatafeed as Tvdatafeed, Interval
except ImportError:
    try:
        from tvDatafeed import Tvdatafeed, Interval
    except ImportError:
        from tvdatafeed import Tvdatafeed, Interval

# --- WEB SUNUCUSU (Render Kapanmasın Diye) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "XAUUSD Sinyal Botu (Gerçek Veri) Çalışıyor!"

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

# --- TEMEL İNDİKATÖR HESAPLAMALARI ---
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
    return bool(final_buy_signal.iloc[-2])

# --- STRATEJİ 1 HESAPLAMASI (FİSHER HARİÇ) ---
def calculate_strategy_one(df):
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

    cond_stoch_rsi = (abs(stoch_k.iloc[-2] / 100) < 9) or (rsi9.iloc[-2] <= 45)
    buy15 = cond_stoch_rsi and (cci15.iloc[-3] < -90 and cci15.iloc[-2] >= -90)
    buy20 = cond_stoch_rsi and (cci20.iloc[-3] < -90 and cci20.iloc[-2] >= -90)
    buy25 = cond_stoch_rsi and (cci25.iloc[-3] < -90 and cci25.iloc[-2] >= -90)

    s_up = 1 if stoch_k.iloc[-2] > stoch_k.iloc[-3] else 0
    r_up = 1 if rsi9.iloc[-2] > rsi9.iloc[-3] else 0
    c15_up = 1 if cci15.iloc[-2] > cci15.iloc[-3] else 0
    c20_up = 1 if cci20.iloc[-2] > cci20.iloc[-3] else 0
    c25_up = 1 if cci25.iloc[-2] > cci25.iloc[-3] else 0

    up_count = s_up + r_up + c15_up + c20_up + c25_up
    trix_up = trix.iloc[-2] > trix.iloc[-3]

    buy_trend = (up_count >= 3) and trix_up
    return bool(buy15 or buy20 or buy25 or buy_trend)

# STRATEJİLER İÇİN AYRI HAFIZA VE HEDEF SÖZLÜKLERİ
last_signals_one = {}
active_targets_one = {}

last_signals_aria = {}
active_targets_aria = {}

def fetch_safe(tv, tf_val):
    try:
        return tv.get_hist(symbol=SYMBOL, exchange=EXCHANGE, interval=tf_val, n_bars=220)
    except Exception:
        return None

# --- PARALEL PERİYOT TARAYICI ---
def monitor_timeframe(tf_name, tf_val):
    print(f"⚡ [{tf_name}] Bağımsız İşçisi Çalıştırıldı.")
    tv = Tvdatafeed()

    active_targets_one[tf_name] = []
    active_targets_aria[tf_name] = []

    while True:
        try:
            df = fetch_safe(tv, tf_val)
            
            if df is None or df.empty:
                tv = Tvdatafeed()
                time.sleep(2)
                df = fetch_safe(tv, tf_val)

            if df is not None and not df.empty:
                high_val = df['high'].iloc[-1]
                close_val = df['close'].iloc[-1]
                tr_tarih_saat = get_tr_time()

                # --- STRATEJİ 1 ---
                strat_one_buy = calculate_strategy_one(df)
                
                # Hedef Kontrolü
                targets_to_remove_one = []
                for target_price in active_targets_one[tf_name]:
                    if high_val >= target_price or close_val >= target_price:
                        msg = (
                            f"🎯 XAU USD LONG 100 PİP HEDEFTE✅\n"
                            f"OANDA:XAUUSD [{tf_name}], price = {target_price:.3f}\n"
                            f"Tarih/Saat = {tr_tarih_saat}"
                        )
                        send_telegram(msg)
                        targets_to_remove_one.append(target_price)
                for tp in targets_to_remove_one:
                    active_targets_one[tf_name].remove(tp)

                # Sinyal Kontrolü
                if strat_one_buy and not last_signals_one.get(tf_name, False):
                    last_signals_one[tf_name] = True
                    target_price = close_val + TARGET_PIPS
                    active_targets_one[tf_name].append(target_price)
                    msg = (
                        f"🚨 XAU USD LONG HEDEF 100 PİP\n"
                        f"OANDA:XAUUSD [{tf_name}], price = {close_val:.3f}\n"
                        f"Tarih/Saat = {tr_tarih_saat}"
                    )
                    send_telegram(msg)
                elif not strat_one_buy:
                    last_signals_one[tf_name] = False


                # --- STRATEJİ 2: ARIA WHISPER ---
                aria_buy = calculate_aria_whisper(df)
                
                # Hedef Kontrolü
                targets_to_remove_aria = []
                for target_price in active_targets_aria[tf_name]:
                    if high_val >= target_price or close_val >= target_price:
                        msg = (
                            f"🎯 XAU USD LONG 100 PİP HEDEFTE✅\n"
                            f"OANDA:XAUUSD [{tf_name}], price = {target_price:.3f}\n"
                            f"Tarih/Saat = {tr_tarih_saat}"
                        )
                        send_telegram(msg)
                        targets_to_remove_aria.append(target_price)
                for tp in targets_to_remove_aria:
                    active_targets_aria[tf_name].remove(tp)

                # Sinyal Kontrolü
                if aria_buy and not last_signals_aria.get(tf_name, False):
                    last_signals_aria[tf_name] = True
                    target_price = close_val + TARGET_PIPS
                    active_targets_aria[tf_name].append(target_price)
                    msg = (
                        f"🚨 XAU USD LONG HEDEF 100 PİP\n"
                        f"OANDA:XAUUSD [{tf_name}], price = {close_val:.3f}\n"
                        f"Tarih/Saat = {tr_tarih_saat}"
                    )
                    send_telegram(msg)
                elif not aria_buy:
                    last_signals_aria[tf_name] = False

            time.sleep(1.5)

        except Exception as e:
            tv = Tvdatafeed()
            time.sleep(3)

def start_bot():
    print(">>> GERÇEK VERİ TABANLI BOT BAŞLATILDI <<<")
    
    tr_start_time = get_tr_time()
    send_telegram(f"🤖 XAUUSD Sinyal Botu (Gerçek Veri) Aktif 🔥\nTarih/Saat = {tr_start_time}")

    intervals = {
        "5m": Interval.in_5_minute,
        "15m": Interval.in_15_minute,
        "30m": Interval.in_30_minute,
        "1h": Interval.in_1_hour,
        "2h": Interval.in_2_hour,
        "3h": Interval.in_3_hour,
        "4h": Interval.in_4_hour
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
