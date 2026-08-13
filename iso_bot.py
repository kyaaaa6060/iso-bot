import os
import time
import requests
from datetime import datetime, timezone, timedelta
from flask import Flask
from threading import Thread
from tradingview_ta import TA_Handler, Interval

# --- WEB SUNUCUSU (Render Kapanmasın Diye) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "İso Bot & Aria Multithread Anında Fırlatıcı Aktif!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- TELEGRAM AYARLARI ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

SYMBOL = "XAUUSD"
EXCHANGE = "OANDA"
TARGET_PIPS = 1.0  # +1.0$ (100 Pip) Hedef

session = requests.Session()

def send_telegram(message):
    """Sinyal yakalandığı an milisaniyeler içinde Telegram'a fırlatır"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        session.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram Gönderim Hatası: {e}")

def get_tr_time():
    """Türkiye Saati (UTC+3)"""
    utc_now = datetime.now(timezone.utc)
    tr_now = utc_now + timedelta(hours=3)
    return tr_now.strftime("%d.%m.%Y - %H:%M:%S")

# --- BAĞIMSIZ ZAMAN DİLİMİ İŞÇİSİ (THREAD) ---
def monitor_timeframe(tf_name, tf_val):
    print(f"🚀 [{tf_name}] Bağımsız İşçisi Çalıştırıldı!")
    
    # Her zaman diliminin kendi özel TradingView bağlantısı var
    handler = TA_Handler(
        symbol=SYMBOL,
        exchange=EXCHANGE,
        screener="forex",
        interval=tf_val
    )

    active_target = None  # Bu periyodun aktif hedefi
    has_signal = False    # Sinyal durumu

    while True:
        try:
            # Anlık veriyi çek
            analysis = handler.get_analysis()
            ind = analysis.indicators

            close_p = ind.get("close")
            high_p = ind.get("high")

            # Technical Indicators
            rsi14 = ind.get("RSI")
            cci20 = ind.get("CCI20")
            sma200 = ind.get("SMA200")
            macd = ind.get("MACD.macd")
            macd_sig = ind.get("MACD.signal")

            # --- SİNYAL MANTIKLARI ---
            aria_buy = (close_p > sma200) and (rsi14 > 40 and rsi14 < 68) and (macd > macd_sig) if (sma200 and rsi14 and macd and macd_sig) else False
            iso_buy = (cci20 < -90) if cci20 else False

            buy_signal = aria_buy or iso_buy
            tr_tarih_saat = get_tr_time()

            # 1. HEDEF KONTROLÜ (Eğer aktif hedef varsa ve fiyat ulaştıysa)
            if active_target and (high_p >= active_target or close_p >= active_target):
                target_msg = (
                    f"XAU USD LONG 100 PİP HEDEFTE✅\n"
                    f"OANDA:XAUUSD [{tf_name}], price = {active_target:.3f}\n"
                    f"Tarih/Saat = {tr_tarih_saat}"
                )
                send_telegram(target_msg)  # ANINDA FIRLAT
                print(f"🎯 [{tf_name}] HEDEF GELEN FİYAT: {active_target:.3f} | {tr_tarih_saat}")
                
                # Hedefe ulaşıldı, sıfırla
                active_target = None
                has_signal = False

            # 2. YENİ SİNYAL KONTROLÜ (Eğer sinyal gelmişse ve daha önce atılmadıysa)
            elif buy_signal and not has_signal:
                active_target = close_p + TARGET_PIPS
                has_signal = True

                signal_msg = (
                    f"XAU USD LONG HEDEF 100 PİP🚨\n"
                    f"OANDA:XAUUSD [{tf_name}], price = {close_p:.3f}\n"
                    f"Tarih/Saat = {tr_tarih_saat}"
                )
                send_telegram(signal_msg)  # ANINDA FIRLAT
                print(f"🚨 [{tf_name}] SİNYAL YAKALANDI: {close_p:.3f} | Hedef: {active_target:.3f} | {tr_tarih_saat}")

            elif not buy_signal and not active_target:
                has_signal = False

            # TradingView Ban Yememek İçin Bağımsız Tarama Aralığı (8 Saniye)
            time.sleep(8)

        except Exception as e:
            # Hata alırsa 3 sn bekle tekrar dene
            time.sleep(3)

# --- BOTU BAŞLATMA ---
def start_bot():
    print(">>> İSO BOT & ARIA BAĞIMSIZ MULTITHREAD BAŞLATILDI <<<")

    # Taranacak zaman dilimleri
    intervals = {
        "5m": Interval.INTERVAL_5_MINUTES,
        "15m": Interval.INTERVAL_15_MINUTES,
        "30m": Interval.INTERVAL_30_MINUTES,
        "1h": Interval.INTERVAL_1_HOUR,
        "2h": Interval.INTERVAL_2_HOURS,
        "4h": Interval.INTERVAL_4_HOURS
    }

    # Her zaman dilimini BAĞIMSIZ bir Thread (kulvar) olarak fırlatıyoruz
    for tf_name, tf_val in intervals.items():
        t = Thread(target=monitor_timeframe, args=(tf_name, tf_val))
        t.daemon = True
        t.start()
        time.sleep(0.2) # Thread'lerin çakışmaması için salaniyelik ara

    while True:
        time.sleep(10)

if __name__ == "__main__":
    # Web Sunucusunu Başlat
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # Botu Başlat
    start_bot()
