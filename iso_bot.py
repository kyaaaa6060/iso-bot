import os
import asyncio
from flask import Flask
from threading import Thread
from telethon import TelegramClient, events

# ==========================================
# 1. FLASK WEB SUNUCUSU (Render & UptimeRobot İçin)
# ==========================================
app = Flask('')

@app.route('/')
def home():
    return "Iso Bot Aktif ve Çalışıyor!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

# ==========================================
# 2. TELEGRAM BİLGİLERİ VE DEĞİŞKENLER
# ==========================================
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")

# Chat ID'lerini al ve integer (tam sayı) tipine dönüştür
SOURCE_CHAT_ID = int(os.environ.get("SOURCE_CHAT_ID", "0"))
TARGET_CHAT_ID = int(os.environ.get("TARGET_CHAT_ID", "0"))

from telethon.sessions import StringSession
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

# ==========================================
# 3. MESAJ DİNLEME VE KOPYALAMA
# ==========================================
@client.on(events.NewMessage())
async def handler(event):
    try:
        # Hangi gruptan/kanaldan mesaj gelirse gelsin Log'a ID'sini ve metnini yazdırır (Hata tespiti için)
        print(f"📥 [YENİ MESAJ YAKALANDI] Chat ID: {event.chat_id} | Metin: {event.raw_text[:30]}...")

        # Eğer mesaj tam olarak bizim takip ettiğimiz kaynak gruptan geldiyse:
        if event.chat_id == SOURCE_CHAT_ID:
            print(f"🎯 Sinyal Hedef Gruba Aktarılıyor... -> {TARGET_CHAT_ID}")
            
            # Mesajı doğrudan hedef kanala ilet/kopyala
            if event.message.media:
                await client.send_message(TARGET_CHAT_ID, event.message.text, file=event.message.media)
            else:
                await client.send_message(TARGET_CHAT_ID, event.message.text)
                
            print("✅ Sinyal Başarıyla Gönderildi!")

    except Exception as e:
        print(f"❌ Mesaj işlenirken hata oluştu: {e}")

# ==========================================
# 4. BOTU BAŞLATMA
# ==========================================
async def main():
    print("🚀 Iso Bot Başlatılıyor...")
    await client.start()
    
    # Başlangıçta hedefe bilgi mesajı gönder
    try:
        await client.send_message(TARGET_CHAT_ID, "🤖 **XAUUSD MetaTrader Spot Bot Aktif!**\nTakip Dilimleri: 5m, 15m, 30m, 1h, 4h")
        print("✅ Başlangıç mesajı hedef kanala atıldı.")
    except Exception as e:
        print(f"⚠️ Başlangıç mesajı atılamadı: {e}")

    print("📡 Kaynak kanal dinleniyor...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    keep_alive()
    asyncio.run(main())
