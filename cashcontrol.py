from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

@app.route('/cashcontrol', methods=['POST'])
def cashcontrol_webhook():
    data = request.json
    if not data:
        return jsonify({"status": "error"}), 400

    action = data.get("action", "SIGNAL")
    ticker = data.get("ticker", "N/A")
    price = data.get("price", "N/A")
    tf = data.get("tf", "N/A")

    emoji = "🟢" if action == "BUY" else "🔴"
    tr_action = "ALIŞ (LONG)" if action == "BUY" else "SATIŞ (SHORT)"

    message = (
        f"{emoji} **CashControl 1 Saatlik Sinyal** {emoji}\n\n"
        f"📊 **Parite:** `{ticker}`\n"
        f"⏱ **Zaman Dilimi:** `{tf}`\n"
        f"🎯 **İşlem:** *{tr_action}*\n"
        f"💰 **Fiyat:** `{price}`"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

    return jsonify({"status": "success"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
