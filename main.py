import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parent / "src"))
load_dotenv()

from database import init_db, should_send_alert, record_alert_sent
from explorer import discover_cheapest_destinations, deep_check_top_candidates
from ingestion import fetch_flight_price
from analyzer import evaluate_price_deal
from ai_evaluator import evaluate_destination
from visualizer import generate_price_chart
from notifier import send_telegram_alert

ROTATION_POOL = ["ITALY", "GREECE", "SPAIN"]

def parse_optional_int(env_key: str) -> int | None:
    val = (os.getenv(env_key) or "").strip()
    if val == "" or val.upper() == "AUTO":
        return None
    return int(val)

SEARCH_CONFIG = {
    "origin": os.getenv("SEARCH_ORIGIN") or "BUD",
    "region_mode": os.getenv("SEARCH_REGION") or "AUTO_ROTATE",
    "month": int(os.getenv("SEARCH_MONTH") or "0"),
    "trip_duration": int(os.getenv("SEARCH_DURATION") or "1"),  # 1 = Hétvége (3-4 nap), 2 = 1 hét, 3 = 2 hét
    "custom_stay_days": parse_optional_int("CUSTOM_STAY_DAYS"), # None (AUTO), vagy 0 (1 napos), 2 (2 napos), 3 (3 napos)
    "max_budget_huf": int(os.getenv("MAX_BUDGET_HUF") or "55000"),
    "top_n_to_verify": int(os.getenv("TOP_N_VERIFY") or "2"),
    # Célzott Fesztivál / Konkrét Város Mód (pl. TARGET_AIRPORT=OTP, TARGET_CITY=Bukarest)
    "target_airport": (os.getenv("TARGET_AIRPORT") or "").strip().upper(),
    "target_city": (os.getenv("TARGET_CITY") or "").strip(),
    "target_dep_date": (os.getenv("TARGET_DEP_DATE") or "").strip(),
    "target_ret_date": (os.getenv("TARGET_RET_DATE") or "").strip(),
}

MIN_AI_SCORE = 7.0

def resolve_target_regions(region_mode: str) -> list[str]:
    mode = region_mode.strip().upper()
    if mode == "AUTO_ROTATE":
        day_of_year = datetime.now().timetuple().tm_yday
        selected = ROTATION_POOL[day_of_year % len(ROTATION_POOL)]
        print(f"🔄 [AUTO-ROTATE] A mai nap régiója (kvóta-optimalizált): {selected}")
        return [selected]
    return [r.strip().upper() for r in mode.split(",") if r.strip()]

def process_verified_flights(verified_flights: list[dict], ranked_results: list):
    """Közös értékelő és riasztó logika a régiós és a célzott kereséshez."""
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

def run_flexible_pipeline():
    print("=== Flight Deal Radar: Rugalmas Dátum-, Egynapos- és Fesztiválkereső ===")
    init_db()
    ranked_results = []

    # 1. ESET: CÉLZOTT VÁROS ÉS DÁTUM MÓD (pl. Beach, Please! Fesztivál - Bukarest OTP)
    if SEARCH_CONFIG["target_airport"] and SEARCH_CONFIG["target_dep_date"]:
        airport = SEARCH_CONFIG["target_airport"]
        city = SEARCH_CONFIG["target_city"] or airport
        dep_date = SEARCH_CONFIG["target_dep_date"]
        ret_date = SEARCH_CONFIG["target_ret_date"]

        if not ret_date and SEARCH_CONFIG["custom_stay_days"] is not None:
            dep_dt = datetime.strptime(dep_date, "%Y-%m-%d")
            ret_date = (dep_dt + timedelta(days=SEARCH_CONFIG["custom_stay_days"])).strftime("%Y-%m-%d")

        print(f"\n🎯 [CÉLZOTT KERESÉS] {SEARCH_CONFIG['origin']} -> {city} ({airport}) | Dátum: {dep_date} -> {ret_date or 'Egyirányú'}")
        exact_flight = fetch_flight_price(
            origin=SEARCH_CONFIG["origin"],
            destination=airport,
            departure_date=dep_date,
            return_date=ret_date or None
        )
        if exact_flight:
            exact_flight["city_name"] = city
            process_verified_flights([exact_flight], ranked_results)
        return

    # 2. ESET: RÉGIÓS EXPLORE KERESÉS (Akár 0 napos / 2-3 napos felülírással)
    target_regions = resolve_target_regions(SEARCH_CONFIG["region_mode"])

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

        verified_flights = deep_check_top_candidates(
            candidates, 
            top_n=SEARCH_CONFIG["top_n_to_verify"],
            custom_stay_days=SEARCH_CONFIG["custom_stay_days"]
        )
        process_verified_flights(verified_flights, ranked_results)

    if ranked_results:
        ranked_results.sort(key=lambda x: x[2]["score"], reverse=True)
        print("\n🏆 === VÉGSŐ AI RANGSOR (Hova érdemes leginkább elmenni?) ===")
        for i, (f, a, ai) in enumerate(ranked_results, 1):
            formatted_p = f"{f['price']:,}".replace(",", " ")
            print(f"  #{i} {f['city_name']} ({f['destination']}) - AI: {ai['score']}/10 | Ár: {formatted_p} Ft ({f['departure_date']} - {f['return_date']})")

if __name__ == "__main__":
    run_flexible_pipeline()