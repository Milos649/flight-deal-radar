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
    
    is_same_day = bool(return_date and return_date == departure_date)

    if return_date:
        params["return_date"] = return_date
        params["type"] = "1"
        if is_same_day:
            # Egynapos mód: reggeli indulás (04:00-12:00) és esti visszaút (17:00-24:00)
            params["outbound_times"] = "4,11"
            params["return_times"] = "17,23"
            print(f"☀️🌙 [EGYNAPOS MÓD] Reggeli odaút + esti visszaút szűrő aktív ({departure_date})")
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
        if is_same_day and "outbound_times" in params:
            print(f"[INFO] Nincs reggel-esti egynapos közvetlen járat ide: {destination} ezen a napon.")
            return None
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
    dep_time_str = flights_segments[0].get("departure_airport", {}).get("time", "") if flights_segments else ""
    
    stops_count = max(0, len(flights_segments) - 1)
    total_duration_min = cheapest.get("total_duration", 0)
    hours, mins = divmod(total_duration_min, 60)
    
    day_trip_tag = " [1 NAPOS: Reggel-Este]" if is_same_day else ""
    duration_str = f"{hours}ó {mins}p (Odaút: {dep_time_str}, {'Közvetlen' if stops_count == 0 else f'{stops_count} átszállás'}){day_trip_tag}"

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
    print(f"[UPSERT MENTVE] {origin} -> {destination} ({dep_date} -> {ret_key}): {price} HUF ({airline})")