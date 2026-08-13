import os
import time
import requests
from datetime import datetime, timezone, timedelta
from flask import Flask
from threading import Thread
from tradingview_ta import TA_Handler, Interval

# --- WEB SUNUCUSU (Render Port Uyarısı Almamak İçin) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "İso Bot & Aria Multithread Anında Fırlatıcı Aktif!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- TELEGRAM VE PİYASA AYARLARI ---
# Render Environment Variables yoksa direkt tırnak içindeki değerleri kullanır
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "BOT_TOKENINIZI_BURAYA_YAZIN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "CHAT_IDINIZI_BURAYA_YAZIN")

SYMBOL = "XAUUSD"
EXCHANGE = "OANDA"
TARGET_PIPS = 1.0  # +1.0$ (100 Pip) Hedef

session = requests.Session()

def send_telegram(message):
    """Sinyal veya log mesajını Telegram'a fırlatır ve sonucu konsola yazar"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        response = session.post(url, json=payload, timeout=10)
        
        # Render Logs ekranında Telegram'dan gelen cevabı görmek için:
        print(f"📩 Telegram Yanıtı [{response.status_code}]: {response.text}")
    except Exception as e:
        print(f"❌ Telegram Kritik Hata: {e}")

def get_tr_time():
    """Türkiye Saati (UTC+3)"""
    utc_now = datetime.now(timezone.utc)
    tr_now = utc_now + timedelta(hours=3)
    return tr_now.strftime("%d.%m.%Y - %H:%M:%S")

# --- BAĞIMSIZ ZAMAN DİLİMİ İŞÇİSİ (THREAD) ---
def monitor_timeframe(tf_name, tf_val):
    print(f"🚀 [{tf_name}] Bağımsız İşçisi Çalıştırıldı!")
    
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

            # 1. HEDEF KONTROLÜ
            if active_target and (high_p >= active_target or close_p >= active_target):
                target_msg = (
                    f"XAU USD LONG 100 PİP HEDEFTE✅\n"
                    f"OANDA:XAUUSD [{tf_name}], price = {active_target:.3f}\n"
                    f"Tarih/Saat = {tr_tarih_saat}"
                )
                send_telegram(target_msg)
                print(f"🎯 [{tf_name}] HEDEF GELEN FİYAT: {active_target:.3f} | {tr_tarih_saat}")
                
                active_target = None
                has_signal = False

            # 2. YENİ SİNYAL KONTROLÜ
            elif buy_signal and not has_signal:
                active_target = close_p + TARGET_PIPS
                has_signal = True

                signal_msg = (
                    f"XAU USD LONG HEDEF 100 PİP🚨\n"
                    f"OANDA:XAUUSD [{tf_name}], price = {close_p:.3f}\n"
                    f"Tarih/Saat = {tr_tarih_saat}"
                )
                send_telegram(signal_msg)
                print(f"🚨 [{tf_name}] SİNYAL YAKALANDI: {close_p:.3f} | Hedef: {active_target:.3f} | {tr_tarih_saat}")

            elif not buy_signal and not active_target:
                has_signal = False

            # 8 saniyede bir bağımsız kontrol
            time.sleep(8)

        except Exception as e:
            time.sleep(3)

# --- BOTU BAŞLATMA VE AÇILIŞ TEST MESAJI ---
def start_bot():
    print(">>> İSO BOT & ARIA BAĞIMSIZ MULTITHREAD BAŞLATILDI <<<")
    
    # 🚨 BOT AÇILDIĞINDA ATILACAK TEST MESAJI:
    tr_start_time = get_tr_time()
    send_telegram(f"🤖 İso Bot & Aria canlıya alındı!\nTüm zaman dilimleri (5m - 4h) taranıyor...\nTarih/Saat = {tr_start_time}")

    # Taranacak zaman dilimleri
    intervals = {
        "5m": Interval.INTERVAL_5_MINUTES,
        "15m": Interval.INTERVAL_15_MINUTES,
        "30m": Interval.INTERVAL_30_MINUTES,
        "1h": Interval.INTERVAL_1_HOUR,
        "2h": Interval.INTERVAL_2_HOURS,
        "4h": Interval.INTERVAL_4_HOURS
    }

    # Her zaman dilimini BAĞIMSIZ bir Thread olarak fırlatıyoruz
    for tf_name, tf_val in intervals.items():
        t = Thread(target=monitor_timeframe, args=(tf_name, tf_val))
        t.daemon = True
        t.start()
        time.sleep(0.5)

    while True:
        time.sleep(10)

if __name__ == "__main__":
    # Web Sunucusunu Başlat
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # Botu Başlat
    start_bot()
