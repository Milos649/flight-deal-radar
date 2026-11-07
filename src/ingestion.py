import os
import requests
from datetime import datetime
from dotenv import load_dotenv
from database import get_db

load_dotenv()
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

def fetch_flight_price(origin: str, destination: str, departure_date: str, return_date: str = None, max_stops: int = 1):
    url = "https://serpapi.com/search.json"
    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": departure_date,
        "stops": str(max_stops),
        "currency": "HUF",
        "hl": "hu",
        "api_key": SERPAPI_KEY
    }
    
    if return_date:
        params["return_date"] = return_date
        params["type"] = "1"
    else:
        params["type"] = "2"

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        print(f"[INGESTION HIBA] Hálózati vagy API hiba ({origin}->{destination}): {e}")
        return None

    best_flights = data.get("best_flights", []) + data.get("other_flights", [])
    if not best_flights:
        if max_stops == 1:
            print(f"[INFO] Nincs közvetlen járat ide: {destination}, keresés max 1 átszállással...")
            return fetch_flight_price(origin, destination, departure_date, return_date, max_stops=2)
        print(f"Nincs találat erre: {origin} -> {destination} ({departure_date})")
        return None

    cheapest = best_flights[0]
    price = cheapest.get("price")
    if not price:
        return None

    flights_segments = cheapest.get("flights", [])
    airline = flights_segments[0].get("airline", "Ismeretlen") if flights_segments else "Ismeretlen"
    
    stops_count = max(0, len(flights_segments) - 1)
    total_duration_min = cheapest.get("total_duration", 0)
    hours, mins = divmod(total_duration_min, 60)
    duration_str = f"{hours}ó {mins}p (Odaút: {'Közvetlen' if stops_count == 0 else f'{stops_count} átszállás'})"

    dep_dt = datetime.strptime(departure_date, "%Y-%m-%d")
    days_left = (dep_dt - datetime.now()).days
    price_insights = data.get("price_insights", {})

    save_price(origin, destination, departure_date, return_date, airline, price, days_left)
    
    return {
        "origin": origin,
        "destination": destination,
        "departure_date": departure_date,
        "return_date": return_date or "",
        "price": price,
        "airline": airline,
        "duration_str": duration_str,
        "stops_count": stops_count,
        "days_left": days_left,
        "price_insights": price_insights
    }

def save_price(origin, destination, dep_date, ret_date, airline, price, days_left):
    ret_key = ret_date or ""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO price_history 
            (origin, destination, departure_date, return_date, airline, price_huf, days_before_departure, scraped_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, DATE('now'))
            ON CONFLICT(origin, destination, departure_date, return_date, scraped_date)
            DO UPDATE SET 
                price_huf = excluded.price_huf,
                airline = excluded.airline,
                scraped_at = CURRENT_TIMESTAMP
        """, (origin, destination, dep_date, ret_key, airline, price, days_left))
    print(f"[UPSERT MENTVE] {origin} -> {destination} ({dep_date}): {price} HUF ({airline})")