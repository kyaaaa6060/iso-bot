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
    return "XAUUSD Sinyal Botu Çalışıyor!"

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

# STRATEJİLER İÇİN HAFIZA VE HEDEF SÖZLÜKLERİ
last_signals_summary = {}
active_targets_summary = {}

# --- PARALEL PERİYOT TARAYICI (TradingView Özet Teknik Analiz) ---
def monitor_timeframe(tf_name, tf_val):
    print(f"⚡ [{tf_name}] Bağımsız İşçisi Çalıştırıldı.")
    
    handler = TA_Handler(
        symbol=SYMBOL,
        exchange=EXCHANGE,
        screener="forex",
        interval=tf_val
    )

    active_targets_summary[tf_name] = []

    while True:
        try:
            analysis = handler.get_analysis()
            recommendation = analysis.summary.get("RECOMMENDATION") # "STRONG_BUY", "BUY", "NEUTRAL", etc.
            ind = analysis.indicators

            close_val = ind.get("close")
            high_val = ind.get("high")
            tr_tarih_saat = get_tr_time()

            # Hedef Kontrolü (100 Pip / 1.0$)
            targets_to_remove = []
            for target_price in active_targets_summary[tf_name]:
                if high_val >= target_price or close_val >= target_price:
                    msg = (
                        f"🎯 XAU USD LONG 100 PİP HEDEFTE✅\n"
                        f"OANDA:XAUUSD [{tf_name}], price = {target_price:.3f}\n"
                        f"Tarih/Saat = {tr_tarih_saat}"
                    )
                    send_telegram(msg)
                    targets_to_remove.append(target_price)
            for tp in targets_to_remove:
                active_targets_summary[tf_name].remove(tp)

            # TradingView Güçlü Al (STRONG_BUY) veya Al (BUY) Sinyali Kontrolü
            is_buy_signal = recommendation in ["STRONG_BUY", "BUY"]

            if is_buy_signal and not last_signals_summary.get(tf_name, False):
                last_signals_summary[tf_name] = True
                target_price = close_val + TARGET_PIPS
                active_targets_summary[tf_name].append(target_price)
                msg = (
                    f"🚨 XAU USD LONG HEDEF 100 PİP [{recommendation}]\n"
                    f"OANDA:XAUUSD [{tf_name}], price = {close_val:.3f}\n"
                    f"Tarih/Saat = {tr_tarih_saat}"
                )
                send_telegram(msg)
            elif not is_buy_signal:
                last_signals_summary[tf_name] = False

            time.sleep(5)

        except Exception as e:
            print(f"⚠️ [{tf_name}] Hata: {e}")
            time.sleep(5)

def start_bot():
    print(">>> TRADINGVIEW ÖZET TABANLI BOT BAŞLATILDI <<<")
    
    tr_start_time = get_tr_time()
    send_telegram(f"🤖 XAUUSD Özet Sinyal Botu Aktif 🔥\nTarih/Saat = {tr_start_time}")

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
