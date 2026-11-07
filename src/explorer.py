import os
import requests
from dotenv import load_dotenv
from ingestion import fetch_flight_price

load_dotenv()
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

REGION_IDS = {
    "GREECE": "/m/035qy",
    "ITALY": "/m/03rjj",
    "SPAIN": "/m/06mkj",
    "EUROPE": "/m/02j9z",
}

def discover_cheapest_destinations(
    origin: str = "BUD",
    region_key: str = "GREECE",
    month: int = 0,
    trip_duration: int = 2,
    max_price_huf: int = 55000,
    max_stops: int = 1
) -> list[dict]:
    url = "https://serpapi.com/search.json"
    arrival_area_id = REGION_IDS.get(region_key.upper(), region_key)

    params = {
        "engine": "google_travel_explore",
        "departure_id": origin,
        "arrival_area_id": arrival_area_id,
        "month": month,
        "travel_duration": trip_duration,
        "stops": str(max_stops),  # 1 = Csak közvetlen járatok (kredit-duplázódás megelőzése)
        "currency": "HUF",
        "hl": "hu",
        "api_key": SERPAPI_KEY
    }

    print(f"\n🌐 [EXPLORE RADAR] Legolcsóbb utak keresése: {origin} -> {region_key} ({month}. hónap)...")
    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code != 200:
            print(f"[HIBA] Explore API hiba: {response.text}")
            return []
        data = response.json()
    except requests.RequestException as e:
        print(f"[HIBA] Hálózati hiba az Explore API hívásakor: {e}")
        return []

    destinations = data.get("destinations", [])
    
    raw_deals = []
    for dest in destinations:
        price = dest.get("flight_price")
        if not price or price > max_price_huf:
            continue

        airport_code = dest.get("destination_airport", {}).get("code")
        city_name = dest.get("name", airport_code)
        start_date = dest.get("start_date")
        end_date = dest.get("end_date")
        airline = dest.get("airline", "Ismeretlen")

        if airport_code and start_date:
            raw_deals.append({
                "origin": origin,
                "destination": airport_code,
                "city_name": city_name,
                "departure_date": start_date,
                "return_date": end_date,
                "explore_price": price,
                "airline": airline
            })

    # Ár szerint növekvő sorrendbe rendezzük
    raw_deals.sort(key=lambda x: x["explore_price"])

    # DEDUPLIKÁCIÓ: Egy reptérkód (pl. BGY, NAP, VCE) csak egyszer szerepelhet!
    unique_deals = []
    seen_airports = set()
    for deal in raw_deals:
        code = deal["destination"]
        if code not in seen_airports:
            seen_airports.add(code)
            unique_deals.append(deal)

    formatted_max = f"{max_price_huf:,}".replace(",", " ")
    print(f"✅ [TALÁLATOK] {len(unique_deals)} db egyedi reptér található {formatted_max} Ft alatt!")
    return unique_deals


def deep_check_top_candidates(candidates: list[dict], top_n: int = 3) -> list[dict]:
    verified_flights = []
    for item in candidates[:top_n]:
        print(f"🔎 [MÉLYELEMZÉS] {item['city_name']} ({item['destination']}): {item['departure_date']} -> {item['return_date']} (Becsült: {item['explore_price']} Ft)")
        
        exact_flight = fetch_flight_price(
            origin=item["origin"],
            destination=item["destination"],
            departure_date=item["departure_date"],
            return_date=item["return_date"]
        )
        
        if exact_flight:
            exact_flight["city_name"] = item["city_name"]
            exact_flight["return_date"] = item["return_date"]
            verified_flights.append(exact_flight)
            
    return verified_flights