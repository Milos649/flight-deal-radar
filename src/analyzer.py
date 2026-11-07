import statistics
from database import get_db

def get_local_price_history(origin: str, destination: str, departure_date: str, return_date: str = "") -> list[int]:
    ret_key = return_date or ""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT price_huf FROM price_history
            WHERE origin = ? AND destination = ? AND departure_date = ? AND return_date = ?
        """, (origin, destination, departure_date, ret_key))
        return [row[0] for row in cursor.fetchall()]

def evaluate_price_deal(flight_data: dict) -> dict:
    current_price = flight_data["price"]
    days_left = flight_data["days_left"]
    insights = flight_data.get("price_insights", {})

    google_history = [point[1] for point in insights.get("price_history", []) if len(point) >= 2]
    local_history = get_local_price_history(
        flight_data["origin"], 
        flight_data["destination"], 
        flight_data["departure_date"],
        flight_data.get("return_date", "")
    )
    
    combined_prices = google_history + local_history
    median_price = int(statistics.median(combined_prices)) if combined_prices else current_price

    typical_range = insights.get("typical_price_range", [median_price, median_price])
    low_typical = typical_range[0] if typical_range else median_price

    discount_pct = round(((median_price - current_price) / median_price) * 100, 1) if median_price > 0 else 0.0

    if current_price <= low_typical * 0.90 or discount_pct >= 20.0:
        recommendation = "BUY_NOW"
        is_deal = True
        reason = f"Kiváló ár! {discount_pct}%-kal a historikus medián ({median_price} Ft) alatt van."
    elif current_price <= low_typical or discount_pct >= 5.0:
        recommendation = "BUY_NOW"
        is_deal = True
        reason = f"Jó vétel! Az ár a szokásos minimum sávban mozog (-{discount_pct}% a mediánhoz képest)."
    elif days_left > 45:
        recommendation = "WAIT"
        is_deal = False
        reason = f"Még {days_left} nap van indulásig. A fapados árak jellemzően 4-7 héttel indulás előtt esnek be."
    else:
        recommendation = "PASS"
        is_deal = False
        reason = f"Drága ({current_price} Ft vs. medián {median_price} Ft), és már közel az indulás."

    return {
        "is_deal": is_deal,
        "recommendation": recommendation,
        "median_price": median_price,
        "discount_pct": discount_pct,
        "reason": reason
    }