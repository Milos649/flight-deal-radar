import sqlite3
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "flights.db"

CITY_DAILY_COSTS_EUR = {
    # Görögország
    "ATH": 65, "SKG": 55, "CFU": 70, "CHQ": 75, "RHO": 75, "JTR": 130, "JMK": 150,
    # Olaszország
    "BGY": 90, "MXP": 95, "BLQ": 80, "CIA": 95, "FCO": 95, "PSA": 75, "NAP": 65, "BRI": 60, "CTA": 60, "VCE": 110, "CAG": 70, "RMI": 70, "PMO": 65,
    # Spanyolország
    "VLC": 70, "MAD": 85, "BCN": 95, "AGP": 75, "PMI": 85, "ALC": 65, "BIO": 80, "SVQ": 70, "LPA": 75, "TFS": 80, "CDT": 60
}
DEFAULT_DAILY_COST_EUR = 75

@contextmanager
def get_db():
    """Biztonságos SQLite kapcsolatkezelő: automatikus commit és garantált lezárás."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_deterministic_daily_cost(airport_code: str) -> int:
    """Visszaadja a város determinisztikus napi költségindexét EUR-ban."""
    return CITY_DAILY_COSTS_EUR.get(airport_code.upper(), DEFAULT_DAILY_COST_EUR)

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            departure_date TEXT NOT NULL,
            return_date TEXT NOT NULL DEFAULT '',
            airline TEXT,
            price_huf INTEGER NOT NULL,
            days_before_departure INTEGER NOT NULL,
            scraped_date TEXT NOT NULL DEFAULT (DATE('now')),
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(origin, destination, departure_date, return_date, scraped_date)
        )
        """)

        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_route_history 
        ON price_history(origin, destination, departure_date, return_date)
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS destination_evaluations (
            destination TEXT NOT NULL,
            travel_month INTEGER NOT NULL,
            ai_score REAL NOT NULL,
            ai_summary TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (destination, travel_month)
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sent_alerts (
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            departure_date TEXT NOT NULL,
            return_date TEXT NOT NULL DEFAULT '',
            last_alerted_price INTEGER NOT NULL,
            alerted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (origin, destination, departure_date, return_date)
        )
        """)

def should_send_alert(origin: str, destination: str, dep_date: str, ret_date: str, current_price: int, cooldown_days: int = 7) -> bool:
    ret_key = ret_date or ""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT last_alerted_price, 
                   CAST((JULIANDAY('now') - JULIANDAY(alerted_at)) AS INTEGER) AS days_since
            FROM sent_alerts
            WHERE origin = ? AND destination = ? AND departure_date = ? AND return_date = ?
        """, (origin, destination, dep_date, ret_key))
        row = cursor.fetchone()

    if not row:
        return True
    
    last_price, days_since = row[0], row[1]
    
    if current_price <= int(last_price * 0.90):
        return True
        
    if days_since is not None and days_since >= cooldown_days and current_price <= last_price:
        return True
        
    return False

def record_alert_sent(origin: str, destination: str, dep_date: str, ret_date: str, price: int):
    ret_key = ret_date or ""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO sent_alerts (origin, destination, departure_date, return_date, last_alerted_price, alerted_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(origin, destination, departure_date, return_date) 
            DO UPDATE SET last_alerted_price = excluded.last_alerted_price, alerted_at = CURRENT_TIMESTAMP
        """, (origin, destination, dep_date, ret_key, price))