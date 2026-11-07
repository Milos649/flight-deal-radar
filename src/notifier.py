import os
import html
import requests
from dotenv import load_dotenv
from database import get_deterministic_daily_cost

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_alert(flight: dict, analysis: dict, ai_review: dict):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[HIBA] Hiányzó Telegram konfiguráció a .env fájlból!")
        return

    score = ai_review["score"]
    score_emoji = "🔥" if score >= 8.5 else "✅" if score >= 7.0 else "⚠️"
    
    # HTML-escape minden külső / AI által generált szövegre!
    pros_text = html.escape(", ".join(ai_review.get("pros", [])))
    cons_text = html.escape(", ".join(ai_review.get("cons", [])))
    weather_vibe = html.escape(str(ai_review.get("weather_vibe", "")))
    news_alert = html.escape(str(ai_review.get("news_alert", "Nincs rendkívüli esemény.")))
    summary_hu = html.escape(str(ai_review.get("summary_hu", "")))
    reason_text = html.escape(str(analysis.get("reason", "")))
    airline_str = html.escape(str(flight.get("airline", "Ismeretlen")))

    raw_city = f"{flight.get('city_name', '')} ({flight['destination']})".strip()
    city_label = html.escape(raw_city)
    date_label = html.escape(f"{flight['departure_date']} ➡️ {flight.get('return_date') or 'Egyirányú'}")
    duration_info = html.escape(str(flight.get("duration_str", "Ismeretlen menetidő")))

    formatted_price = f"{flight['price']:,}".replace(",", " ")
    formatted_median = f"{analysis['median_price']:,}".replace(",", " ")
    
    disc = analysis["discount_pct"]
    discount_label = f"-{disc}%" if disc >= 0 else f"+{abs(disc)}%"

    daily_eur = get_deterministic_daily_cost(flight["destination"])

    gf_link = (
        f"https://www.google.com/travel/flights?q=Flights%20to%20{flight['destination']}"
        f"%20from%20{flight['origin']}%20on%20{flight['departure_date']}"
        + (f"%20through%20{flight['return_date']}" if flight.get("return_date") else "")
    )

    message = (
        f"🚨 <b>OKOS UTAZÁSI RADAR TALÁLAT!</b> 🚨\n\n"
        f"✈️ <b>Úti cél:</b> {flight['origin']} ➡️ <b>{city_label}</b> ({airline_str})\n"
        f"⏱ <b>Járat infó:</b> {duration_info}\n"
        f"📅 <b>Legolcsóbb időszak:</b> {date_label} <i>({flight['days_left']} nap múlva)</i>\n"
        f"💰 <b>Repjegy (oda-vissza):</b> <b>{formatted_price} Ft</b> <i>({discount_label} a {formatted_median} Ft mediánhoz képest)</i>\n"
        f"🏨 <b>Kinti napi költségindex:</b> ~{daily_eur} EUR / nap <i>(Numbeo alapú)</i>\n"
        f"📊 <b>AirHint javaslat:</b> <code>{analysis['recommendation']}</code> – {reason_text}\n\n"
        f"{score_emoji} <b>AI Értékelés: {score}/10</b>\n"
        f"🌤 <b>Időjárás:</b> {weather_vibe}\n"
        f"📰 <b>Hír Radar:</b> {news_alert}\n"
        f"👍 <b>Mellette:</b> {pros_text}\n"
        f"👎 <b>Ellene:</b> {cons_text}\n\n"
        f"💬 <i>\"{summary_hu}\"</i>\n\n"
        f"🔗 <a href='{gf_link}'>Megnyitás Google Flights-on</a>"
    )

    chart_path = flight.get("chart_path", "")
    if chart_path and os.path.exists(chart_path):
        photo_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        with open(chart_path, "rb") as photo:
            requests.post(photo_url, files={"photo": photo}, data={"chat_id": TELEGRAM_CHAT_ID}, timeout=15)

    text_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    response = requests.post(text_url, json=payload, timeout=15)
        
    if response.status_code == 200:
        print(f"[TELEGRAM] Értesítés sikeresen elküldve ide: {flight['destination']}!")
    else:
        print(f"[TELEGRAM HIBA] {response.status_code}: {response.text}")