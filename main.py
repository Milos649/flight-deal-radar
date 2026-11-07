import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parent / "src"))
load_dotenv()

from database import init_db, should_send_alert, record_alert_sent
from explorer import discover_cheapest_destinations, deep_check_top_candidates
from analyzer import evaluate_price_deal
from ai_evaluator import evaluate_destination
from visualizer import generate_price_chart
from notifier import send_telegram_alert

ROTATION_POOL = ["ITALY", "GREECE", "SPAIN"]

SEARCH_CONFIG = {
    "origin": os.getenv("SEARCH_ORIGIN") or "BUD",
    "region_mode": os.getenv("SEARCH_REGION") or "AUTO_ROTATE",
    "month": int(os.getenv("SEARCH_MONTH") or "0"),
    "trip_duration": int(os.getenv("SEARCH_DURATION") or "2"),
    "max_budget_huf": int(os.getenv("MAX_BUDGET_HUF") or "55000"),
    "top_n_to_verify": int(os.getenv("TOP_N_VERIFY") or "2")
}

MIN_AI_SCORE = 7.0

def resolve_target_regions(region_mode: str) -> list[str]:
    """
    Meghatározza a lekérdezendő régió(ka)t.
    AUTO_ROTATE esetén az év napja alapján forgatja a régiókat, hogy a havi 100-as
    ingyenes SerpApi kvótán belül maradjon a napi ütemezett futás.
    """
    mode = region_mode.strip().upper()
    if mode == "AUTO_ROTATE":
        day_of_year = datetime.now().timetuple().tm_yday
        selected = ROTATION_POOL[day_of_year % len(ROTATION_POOL)]
        print(f"🔄 [AUTO-ROTATE] A mai nap régiója (kvóta-optimalizált): {selected}")
        return [selected]
    return [r.strip().upper() for r in mode.split(",") if r.strip()]

def run_flexible_pipeline():
    print("=== Flight Deal Radar: Rugalmas Dátum- és Régiókereső ===")
    init_db()

    target_regions = resolve_target_regions(SEARCH_CONFIG["region_mode"])
    ranked_results = []

    for region in target_regions:
        candidates = discover_cheapest_destinations(
            origin=SEARCH_CONFIG["origin"],
            region_key=region,
            month=SEARCH_CONFIG["month"],
            trip_duration=SEARCH_CONFIG["trip_duration"],
            max_price_huf=SEARCH_CONFIG["max_budget_huf"]
        )

        if not candidates:
            print(f"Nincs a büdzsén belüli találat ebben a régióban: {region}")
            continue

        print(f"\n📋 [ELŐZETES TOPLISTA ({region}) - Legolcsóbb egyedi repterek]:")
        for idx, c in enumerate(candidates, 1):
            formatted_exp = f"{c['explore_price']:,}".replace(",", " ")
            print(f"  {idx}. {c['city_name']} ({c['destination']}): {formatted_exp} Ft | {c['departure_date']} -> {c['return_date']} ({c['airline']})")

        verified_flights = deep_check_top_candidates(candidates, top_n=SEARCH_CONFIG["top_n_to_verify"])

        for flight_data in verified_flights:
            dest = flight_data["destination"]
            dep_date = flight_data["departure_date"]
            ret_date = flight_data.get("return_date", "")

            analysis = evaluate_price_deal(flight_data)
            print(f"\n📊 [ELEMZÉS - {flight_data['city_name']}] Javaslat: {analysis['recommendation']} | {analysis['reason']}")

            if analysis["is_deal"] and flight_data["price"] <= SEARCH_CONFIG["max_budget_huf"]:
                ai_review = evaluate_destination(
                    dest, 
                    dep_date, 
                    city_name=flight_data.get("city_name", ""), 
                    airline=flight_data.get("airline", "")
                )
                print(f"🤖 [AI PONTSZÁM] {flight_data['city_name']}: {ai_review['score']}/10 | 📰 Hírek: {ai_review.get('news_alert')}")

                if not ai_review.get("is_fallback", False):
                    ranked_results.append((flight_data, analysis, ai_review))

                if not ai_review.get("is_fallback", False) and ai_review["score"] >= MIN_AI_SCORE:
                    if should_send_alert(flight_data["origin"], dest, dep_date, ret_date, flight_data["price"]):
                        chart_path = generate_price_chart(flight_data)
                        flight_data["chart_path"] = chart_path
                        
                        send_telegram_alert(flight_data, analysis, ai_review)
                        record_alert_sent(flight_data["origin"], dest, dep_date, ret_date, flight_data["price"])
                    else:
                        print(f"🔕 [SPAM SZŰRŐ] Erről az árról ({flight_data['price']} Ft) már küldtünk értesítést.")
            elif analysis["is_deal"]:
                print(f"⚠️ [SZŰRVE] Jó ár-érték arány, de a valós idejű ár ({flight_data['price']} Ft) meghaladja a max_budget_huf ({SEARCH_CONFIG['max_budget_huf']} Ft) keretet.")

    if ranked_results:
        ranked_results.sort(key=lambda x: x[2]["score"], reverse=True)
        print("\n🏆 === VÉGSŐ AI RANGSOR (Hova érdemes leginkább elmenni?) ===")
        for i, (f, a, ai) in enumerate(ranked_results, 1):
            formatted_p = f"{f['price']:,}".replace(",", " ")
            print(f"  #{i} {f['city_name']} ({f['destination']}) - AI: {ai['score']}/10 | Ár: {formatted_p} Ft ({f['departure_date']} - {f['return_date']})")

if __name__ == "__main__":
    run_flexible_pipeline()