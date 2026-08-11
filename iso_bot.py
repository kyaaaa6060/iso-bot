import os
import time
import requests
import pandas as pd
import numpy as np
from flask import Flask
from threading import Thread

# --- TVDATAFEED IMPORT İŞLEMİ (Linux/Render Harf Duyarlılık Koruması) ---
try:
    from tvDatafeed import TvDatafeed as Tvdatafeed, Interval
except ImportError:
    try:
        from tvDatafeed import Tvdatafeed, Interval
    except ImportError:
        from tvdatafeed import Tvdatafeed, Interval

# --- WEB SUNUCUSU (Render Port Binding & UptimeRobot İçin) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "İso Bot 7/24 Aktif!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- AYARLAR & CONFIG ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")
SYMBOL = "XAUUSD"
EXCHANGE = "OANDA"
TARGET_PIPS = 1.0  # Gold (XAUUSD) için 100 pip = 1.0$ (1 tam dolar)

# Telegram Mesaj Gönderme
def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        }
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Gönderim Hatası: {e}")

# --- SAF PANDAS İNDİKATÖR FONKSİYONLARI ---
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

# --- İNDİKATÖR & SİNYAL HESAPLAMA ---
def calculate_iso_bot(df):
    if df is None or len(df) < 50:
        return False, ""

    close = df['close']
    high = df['high']
    low = df['low']

    # 1. Stoch RSI (8, 10, 3)
    rsi8 = calc_rsi(close, length=8)
    if rsi8 is None:
        return False, ""

    highest_rsi = rsi8.rolling(10).max()
    lowest_rsi = rsi8.rolling(10).min()
    stoch_raw = np.where(highest_rsi == lowest_rsi, 0.0, (rsi8 - lowest_rsi) / (highest_rsi - lowest_rsi))
    stoch_k = pd.Series(stoch_raw, index=df.index).rolling(3).mean() * 100

    # 2. RSI (7)
    rsi9 = calc_rsi(close, length=7)

    # 3. CCI (15, 20, 25)
    cci15 = calc_cci(high, low, close, length=15)
    cci20 = calc_cci(high, low, close, length=20)
    cci25 = calc_cci(high, low, close, length=25)

    # 4. TRIX (18)
    ema1 = calc_ema(close, length=18)
    ema2 = calc_ema(ema1, length=18)
    ema3 = calc_ema(ema2, length=18)
    trix = 100 * (ema3 - ema3.shift(1)) / ema3.shift(1)

    # 5. Fisher Transform (18)
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

    # --- SİNYAL KOŞULLARI (Son Onaylanmış Mum İçin: iloc[-2]) ---
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

# --- TARAMA & HEDEF TAKİP DÖNGÜSÜ ---
def start_bot():
    print("İso Bot tarama döngüsü başlatılıyor...")
    tv = Tvdatafeed()
    last_signals = {}
    active_targets = {}  # { "5m": target_price, ... }

    intervals = {
        "5m": Interval.in_5_minute,
        "15m": Interval.in_15_minute,
        "30m": Interval.in_30_minute,
        "1h": Interval.in_1_hour,
        "2h": Interval.in_2_hour,
        "4h": Interval.in_4_hour
    }

    # İLK AÇILIŞTA MEVCUT MUM ZAMANLARINI HAFIZAYA AL
    for tf_name, tf_val in intervals.items():
        try:
            df = tv.get_hist(symbol=SYMBOL, exchange=EXCHANGE, interval=tf_val, n_bars=10)
            if df is not None and not df.empty:
                last_signals[tf_name] = f"{tf_name}_{str(df.index[-2])}"
        except Exception:
            pass

    # ANA TARAMA DÖNGÜSÜ
    while True:
        try:
            for tf_name, tf_val in intervals.items():
                try:
                    df = tv.get_hist(symbol=SYMBOL, exchange=EXCHANGE, interval=tf_val, n_bars=50)
                    if df is not None and not df.empty:
                        buy, sig_type = calculate_iso_bot(df)
                        last_bar_time = df.index[-2]
                        last_price = df['close'].iloc[-2]
                        current_high = df['high'].iloc[-1]   
                        current_close = df['close'].iloc[-1] 
                        formatted_time = last_bar_time.strftime('%Y-%m-%dT%H:%M:%SZ')

                        # 1. HEDEF KONTROLÜ (Debug Log Destekli)
                        if tf_name in active_targets:
                            target_price = active_targets[tf_name]
                            print(f"DEBUG [{tf_name}]: Aktif Hedef={target_price:.3f} | Anlık High={current_high:.3f}")
                            
                            if current_high >= target_price or current_close >= target_price:
                                target_msg = f"XAU USD LONG 100 PİP HEDEFTE✅\n" \
                                             f"OANDA:XAUUSD, price = {target_price:.3f}\n" \
                                             f"DateTime = {formatted_time}"
                                send_telegram(target_msg)
                                print(f"[{tf_name}] Hedef Ulaşıldı ve Gönderildi: {target_price}")
                                del active_targets[tf_name]

                        # 2. YENİ GİRİŞ SİNYALİ KONTROLÜ
                        key = f"{tf_name}_{str(last_bar_time)}"
                        if buy and last_signals.get(tf_name) != key:
                            last_signals[tf_name] = key
                            target_price = last_price + TARGET_PIPS
                            active_targets[tf_name] = target_price

                            signal_msg = f"XAU USD LONG HEDEF 100 PİP🚨\n" \
                                         f"OANDA:XAUUSD, price = {last_price:.3f}\n" \
                                         f"DateTime = {formatted_time}"

                            send_telegram(signal_msg)
                            print(f"[{tf_name}] Sinyal gönderildi: {sig_type} - Fiyat: {last_price} - Hedef: {target_price}")
                        elif not buy:
                            last_signals[tf_name] = key

                except Exception as e:
                    print(f"[{tf_name}] Veri çekme hatası: {e}")
                    if "Too Many Requests" in str(e) or "Rate limited" in str(e):
                        time.sleep(60)

                time.sleep(2)

            time.sleep(10)

        except Exception as e:
            print(f"Genel Tarama Hatası: {e}")
            time.sleep(30)

if __name__ == "__main__":
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    start_bot()
