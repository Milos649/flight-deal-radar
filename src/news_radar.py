import urllib.parse
import xml.etree.ElementTree as ET
import requests

def fetch_destination_news(city_name: str, airline: str = "") -> list[str]:
    """
    Lekéri a legfrissebb híreket a célállomásról és a légitársaságról a Google News RSS-ből (0 API költség).
    Fókusz: sztrájkok, időjárási anomáliák, turizmus, repülőjegy árak.
    """
    query = f"{city_name} travel OR flights OR weather OR strike"
    if airline and airline != "Ismeretlen":
        query += f" OR {airline}"
        
    encoded_query = urllib.parse.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}+when:14d&hl=en-US&gl=US&ceid=US:en"

    try:
        response = requests.get(rss_url, timeout=5)
        if response.status_code != 200:
            return []

        root = ET.fromstring(response.content)
        headlines = []
        # Legfeljebb az 5 legfrissebb releváns szalagcímet szedjük ki
        for item in root.findall("./channel/item")[:5]:
            title = item.find("title")
            if title is not None and title.text:
                headlines.append(title.text)
        return headlines
    except Exception as e:
        print(f"[HÍR RADAR HIBA] Nem sikerült lekérni a híreket: {e}")
        return []