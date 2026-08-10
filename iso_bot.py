import os
import time
import requests
import pandas as pd
import numpy as np
import pandas_ta as ta
from tvdatafeed import Tvdatafeed, Interval
from flask import Flask
from threading import Thread

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

# Telegram Mesaj Gönderme
def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Gönderim Hatası: {e}")

# --- İNDİKATÖR & SİNYAL HESAPLAMA ---
def calculate_iso_bot(df):
    if df is None or len(df) < 50:
        return False, ""

    close = df['close']
    high = df['high']
    low = df['low']

    # 1. Stoch RSI (8, 10, 3)
    rsi8 = ta.rsi(close, length=8)
    if rsi8 is None:
        return False, ""

    highest_rsi = rsi8.rolling(10).max()
    lowest_rsi = rsi8.rolling(10).min()
    stoch_raw = np.where(highest_rsi == lowest_rsi, 0.0, (rsi8 - lowest_rsi) / (highest_rsi - lowest_rsi))
    stoch_k = pd.Series(stoch_raw, index=df.index).rolling(3).mean() * 100

    # 2. RSI (7)
    rsi9 = ta.rsi(close, length=7)

    # 3. CCI (15, 20, 25)
    cci15 = ta.cci(high, low, close, length=15)
    cci20 = ta.cci(high, low, close, length=20)
    cci25 = ta.cci(high, low, close, length=25)

    # 4. TRIX (18)
    ema1 = ta.ema(close, length=18)
    ema2 = ta.ema(ema1, length=18)
    ema3 = ta.ema(ema2, length=18)
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

# --- TARAMA DÖNGÜSÜ ---
def start_bot():
    print("İso Bot tarama döngüsü başlatılıyor...")
    tv = Tvdatafeed()
    last_signals = {}

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
                try:
                    df = tv.get_hist(symbol=SYMBOL, exchange=EXCHANGE, interval=tf_val, n_bars=100)
                    if df is not None and not df.empty:
                        buy, sig_type = calculate_iso_bot(df)
                        last_bar_time = str(df.index[-2])

                        key = f"{tf_name}_{last_bar_time}"
                        if buy and last_signals.get(tf_name) != key:
                            last_signals[tf_name] = key
                            last_price = df['close'].iloc[-2]

                            msg = f"🚨 <b>İSO BOT AL SİNYALİ</b>\n" \
                                  f"📌 <b>Parite:</b> {SYMBOL}\n" \
                                  f"⏱ <b>Zaman Dilimi:</b> {tf_name}\n" \
                                  f"🎯 <b>Sinyal Tipi:</b> {sig_type}\n" \
                                  f"💵 <b>Fiyat:</b> {last_price}\n" \
                                  f"✅ <i>Kapanış ile onaylandı!</i>"

                            send_telegram(msg)
                            print(f"[{tf_name}] Sinyal gönderildi: {sig_type} - Fiyat: {last_price}")
                except Exception as e:
                    print(f"[{tf_name}] Veri çekme hatası: {e}")
                    if "Too Many Requests" in str(e) or "Rate limited" in str(e):
                        print("TradingView kısıtlaması algılandı, 60 saniye dinleniliyor...")
                        time.sleep(60)

                # İstekler arasına 2.5 saniye gecikme ekliyoruz (Rate limit koruması)
                time.sleep(2.5)

            # Her tam tarama turu bittiğinde 60 saniye bekle
            time.sleep(60)

        except Exception as e:
            print(f"Genel Tarama Hatası: {e}")
            time.sleep(30)

if __name__ == "__main__":
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    start_bot()
