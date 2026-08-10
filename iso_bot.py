# --- WEB SUNUCUSU (Render & UptimeRobot İçin) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "İso Bot 7/24 Aktif!"

def run_flask():
    # Render'ın dinamik olarak atadığı PORT değişkenini okuyoruz
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    # 1. Önce Flask web sunucusunu başlatıyoruz (Render portu anında tespit etsin)
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # 2. Ardından indikator tarama döngüsünü başlatıyoruz
    start_bot()
