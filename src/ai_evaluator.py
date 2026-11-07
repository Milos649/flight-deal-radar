import os
import json
import time
from datetime import datetime
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types, errors
from database import get_db, get_deterministic_daily_cost
from news_radar import fetch_destination_news

load_dotenv()

class DestinationReview(BaseModel):
    score: float = Field(description="Pontszám 1.0-tól 10.0-ig (időjárás, élmény és aktuális hírek alapján).")
    weather_vibe: str = Field(description="Rövid, 3-5 szavas összegzés a várható időjárásról.")
    news_alert: str = Field(description="1 mondatos összegzés az aktuális hírekről (van-e sztrájk, vihar, vagy minden nyugodt).")
    pros: list[str] = Field(description="Top 2-3 érv az utazás mellett.")
    cons: list[str] = Field(description="1-2 esetleges hátrány.")
    summary_hu: str = Field(description="Tömör, 2 mondatos magyar ajánló a Telegram üzenetbe.")

def evaluate_destination(destination_code: str, departure_date: str, city_name: str = "", airline: str = "") -> dict:
    travel_month = datetime.strptime(departure_date, "%Y-%m-%d").month
    target_name = city_name if city_name else destination_code
    deterministic_eur = get_deterministic_daily_cost(destination_code)

    cached = get_cached_evaluation(destination_code, travel_month)
    if cached and "news_alert" in cached:
        print(f"[CACHE HIT - <24h] AI értékelés betöltve innen: {target_name} ({travel_month}. hó)")
        cached["daily_budget_eur"] = deterministic_eur
        cached["is_fallback"] = False
        return cached

    headlines = fetch_destination_news(target_name, airline)
    news_context = "\n".join(f"- {h}" for h in headlines) if headlines else "Nincs különösebb rendkívüli hír."

    client = genai.Client(
        api_key=os.getenv("GEMINI_API_KEY"),
        http_options={"timeout": 15000}
    )
    
    prompt = f"""
    Egy utazó olcsó repülőjegyet talált ide: {target_name} ({destination_code}), 
    légitársaság: {airline}, az utazás hónapja: {travel_month}. hónap.
    A város determinisztikus napi költségindexe: ~{deterministic_eur} EUR/nap.
    
    FRISS HÍREK A TÉRSÉGBŐL ÉS A LÉGITÁRSASÁGRÓL (elmúlt 14 nap):
    {news_context}
    
    Értékeld kritikusan:
    1. Mennyire jó ötlet ide utazni ebben a hónapban (időjárás, nyitvatartás, tömeg)?
    2. A fenti friss hírek alapján van-e bármilyen veszély (sztrájk, lezárás, rossz idő) vagy pozitívum?
    """

    # A Google API által a te fiókodhoz hivatalosan elvárt modellek!
    models_to_try = [
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite"
    ]
    
    for model_name in models_to_try:
        try:
            print(f"[AI + HÍR RADAR] Elemzés futtatása ({model_name})...")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=DestinationReview,
                    temperature=0.3
                )
            )
            result_dict = json.loads(response.text)
            result_dict["daily_budget_eur"] = deterministic_eur
            result_dict["is_fallback"] = False
            save_evaluation_to_cache(destination_code, travel_month, result_dict)
            print(f"[AI SIKER] Valódi LLM válasz érkezett ({model_name} -> {result_dict['score']}/10)")
            return result_dict
            
        except errors.APIError as e:
            print(f"[AI API HIBA] {model_name} ({e.code}): {e.message}")
            time.sleep(1.0)
        except Exception as e:
            print(f"[AI HÁLÓZATI HIBA] {model_name} ({type(e).__name__}): {e}")
            time.sleep(1.0)

    print("[KRITIKUS] Minden AI modell elbukott! Fallback aktiválva (score=0.0, riasztás letiltva).")
    return {
        "score": 0.0,
        "is_fallback": True,
        "weather_vibe": "Nem elérhető (AI hiba)",
        "daily_budget_eur": deterministic_eur,
        "news_alert": "AI elemzés nem volt elérhető, ellenőrizd a híreket manuálisan!",
        "pros": [],
        "cons": ["AI szolgáltatás átmenetileg nem elérhető"],
        "summary_hu": "Az AI értékelő nem tudta ellenőrizni a célállomást."
    }

def get_cached_evaluation(dest: str, month: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ai_score, ai_summary FROM destination_evaluations 
            WHERE destination = ? AND travel_month = ?
              AND (JULIANDAY('now') - JULIANDAY(updated_at)) < 1.0
        """, (dest, month))
        row = cursor.fetchone()
    return json.loads(row[1]) if row else None

def save_evaluation_to_cache(dest: str, month: int, data: dict):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO destination_evaluations (destination, travel_month, ai_score, ai_summary, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (dest, month, data["score"], json.dumps(data, ensure_ascii=False)))