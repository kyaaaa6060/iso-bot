import time
from datetime import datetime, timezone, timedelta
import requests
from tradingview_ta import TA_Handler, Interval

# --- TELEGRAM BOT AYARLARI ---
TELEGRAM_TOKEN = "BOT_TOKENINIZI_BURAYA_YAZIN"
CHAT_ID = "CHAT_IDINIZI_BURAYA_YAZIN"

def send_telegram_msg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram mesaj gönderme hatası: {e}")

# --- TRADINGVIEW HANDLER (OANDA:XAUUSD) ---
handler = TA_Handler(
    symbol="XAUUSD",
    exchange="OANDA",
    screener="forex",
    interval=Interval.INTERVAL_1_MINUTE # Dilediğiniz zaman dilimine ayarlayabilirsiniz
)

# --- DEĞİŞKENLER ---
has_target = False
target_price = 0.0

print("Bot çalışıyor, XAUUSD sinyalleri taranıyor...")

while True:
    try:
        # Indikatör analiz verilerini al
        analysis = handler.get_analysis()
        ind = analysis.indicators
        
        close_price = ind.get("close")
        high_price = ind.get("high")
        
        # --- STRATEJİ HESAPLAMALARI ---
        # 1. Aria Whisper Koşulları
        sma200 = ind.get("SMA200")
        rsi14 = ind.get("RSI")
        macd = ind.get("MACD.macd")
        macd_signal = ind.get("MACD.signal")
        ema4 = ind.get("EMA4") if ind.get("EMA4") else ind.get("EMA5") # Yedekli alım
        ema5 = ind.get("EMA5")
        open_price = ind.get("open")
        volume = ind.get("volume")
        vol_ma = ind.get("volume.sMA_20") if ind.get("volume.sMA_20") else 1.0

        aria_uptrend = close_price > sma200 if sma200 else True
        aria_bull_candle = close_price > open_price
        aria_bear_candle = close_price < open_price
        aria_high_vol = volume > (vol_ma * 1.5) if (volume and vol_ma) else False
        aria_momentum = (rsi14 > 40) and (rsi14 < 68) and (macd > macd_signal) if (rsi14 and macd and macd_signal) else False
        aria_ribbon = ema4 > ema5 if (ema4 and ema5) else True
        aria_not_overextended = ((close_price - ema4) / ema4 * 100) < 1.5 if ema4 else True

        aria_strong_buy = aria_uptrend and (aria_bull_candle or (aria_bear_candle and aria_high_vol and aria_momentum))
        aria_buy_signal = aria_strong_buy and aria_ribbon and aria_not_overextended

        # 2. Iso Bot Koşulları
        cci20 = ind.get("CCI20")
        rsi8 = ind.get("RSI[1]") if ind.get("RSI[1]") else rsi14
        
        iso_buy_signal = False
        if cci20 and rsi8:
            iso_buy_signal = (cci20 < -90) and (rsi8 <= 45)

        # Birleşik Al Sinyali
        final_buy = aria_buy_signal or iso_buy_signal

        # --- TÜRKİYE SAATİ FORMATLAMA (UTC+3) ---
        utc_now = datetime.now(timezone.utc)
        tr_now = utc_now + timedelta(hours=3)
        tr_tarih_saat = tr_now.strftime("%d.%m.%Y - %H:%M:%S")

        # --- SİNYAL VE HEDEF MANTIĞI ---
        # 1. Yeni AL Sinyali Geldiğinde
        if final_buy and not has_target:
            target_price = close_price + 1.0  # +1$ Target (100 Pips)
            has_target = True

            mesaj_signal = f"XAU USD LONG HEDEF 100 PİP🚨\nOANDA:XAUUSD, price = {close_price:.3f}\nTarih/Saat = {tr_tarih_saat}"
            send_telegram_msg(mesaj_signal)
            print(f"[{tr_tarih_saat}] AL Sinyali Gönderildi. Giriş: {close_price:.3f} | Hedef: {target_price:.3f}")

        # 2. +1$ Hedefe Ulaşıldığında
        if has_target and high_price >= target_price:
            mesaj_target = f"XAU USD LONG 100 PİP HEDEFTE✅\nOANDA:XAUUSD, price = {target_price:.3f}\nTarih/Saat = {tr_tarih_saat}"
            send_telegram_msg(mesaj_target)
            print(f"[{tr_tarih_saat}] SAT Sinyali Gönderildi. Hedefe Ulaşıldı: {target_price:.3f}")
            
            has_target = False  # Hedefe ulaşıldı, bir sonraki AL sinyalini bekle

    except Exception as e:
        print(f"Hata oluştu, tekrar deneniyor: {e}")

    # 10 saniyede bir kontrol et
    time.sleep(10)
