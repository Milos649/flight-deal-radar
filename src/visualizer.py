import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from database import BASE_DIR, get_db

def generate_price_chart(flight_data: dict) -> str:
    """
    Összefésüli a SerpApi 60 napos ártörténetét és a lokális SQLite méréseket,
    majd kirajzolja a teljes árgörbét.
    """
    origin = flight_data["origin"]
    destination = flight_data["destination"]
    dep_date = flight_data["departure_date"]
    ret_date = flight_data.get("return_date", "")

    insights = flight_data.get("price_insights", {})
    google_raw = insights.get("price_history", [])
    records = []
    
    for point in google_raw:
        if len(point) >= 2:
            dt = pd.to_datetime(point[0], unit="s")
            records.append({"dt": dt, "price_huf": point[1]})

    query = """
        SELECT scraped_at, price_huf 
        FROM price_history 
        WHERE origin = ? AND destination = ? AND departure_date = ? AND return_date = ?
        ORDER BY scraped_at ASC
    """
    with get_db() as conn:
        local_df = pd.read_sql_query(query, conn, params=(origin, destination, dep_date, ret_date))

    for _, row in local_df.iterrows():
        records.append({"dt": pd.to_datetime(row["scraped_at"]), "price_huf": row["price_huf"]})

    if not records:
        return ""

    df = pd.DataFrame(records).sort_values("dt").drop_duplicates(subset=["dt"])

    plt.figure(figsize=(9, 4.5))
    plt.plot(df["dt"], df["price_huf"], marker="o", markersize=4, linestyle="-", color="#1f77b4", linewidth=2, label="Ártörténet")
    
    last_dt = df["dt"].iloc[-1]
    last_price = int(df["price_huf"].iloc[-1])
    formatted_last = f"{last_price:,}".replace(",", " ")
    
    plt.scatter(last_dt, last_price, color="#d62728", s=110, zorder=5, label="Jelenlegi ár")
    plt.annotate(
        f" {formatted_last} Ft", 
        (last_dt, last_price),
        textcoords="offset points", 
        xytext=(5, 5), 
        color="#d62728", 
        fontsize=11, 
        fontweight="bold"
    )

    plt.title(f"60 Napos Ártrend: {origin} ➡️ {destination} ({dep_date})", fontsize=13, pad=12, fontweight="bold")
    plt.xlabel("Dátum", fontsize=10)
    plt.ylabel("Oda-vissza ár (HUF)", fontsize=10)
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend(loc="upper right")
    
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%m.%d"))
    plt.xticks(rotation=25)
    plt.tight_layout()

    img_path = BASE_DIR / "data" / f"chart_{origin}_{destination}.png"
    plt.savefig(img_path, dpi=150)
    plt.close()
    
    return str(img_path)