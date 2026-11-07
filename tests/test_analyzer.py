import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parent.parent / "src"))

from analyzer import evaluate_price_deal
from database import get_deterministic_daily_cost, DEFAULT_DAILY_COST_EUR

class TestFlightAnalyzer(unittest.TestCase):

    @patch("analyzer.get_local_price_history")
    def test_buy_now_high_discount(self, mock_local_history):
        """Ha az ár >20%-kal a kombinált medián alatt van, BUY_NOW és is_deal=True kell legyen."""
        mock_local_history.return_value = [30000, 32000]
        flight_data = {
            "origin": "BUD",
            "destination": "ATH",
            "departure_date": "2027-02-26",
            "return_date": "2027-03-05",
            "price": 18000,
            "days_left": 60,
            "price_insights": {
                "price_history": [[1700000000, 28000], [1700086400, 30000]],
                "typical_price_range": [25000, 35000]
            }
        }
        result = evaluate_price_deal(flight_data)
        self.assertTrue(result["is_deal"])
        self.assertEqual(result["recommendation"], "BUY_NOW")
        self.assertGreaterEqual(result["discount_pct"], 20.0)

    @patch("analyzer.get_local_price_history")
    def test_wait_when_expensive_and_far_out(self, mock_local_history):
        """Ha az ár drága, de még >45 nap van indulásig, javasoljon WAIT-et."""
        mock_local_history.return_value = [20000]
        flight_data = {
            "origin": "BUD",
            "destination": "BCN",
            "departure_date": "2027-04-10",
            "return_date": "2027-04-17",
            "price": 35000,
            "days_left": 90,
            "price_insights": {
                "price_history": [[1700000000, 22000], [1700086400, 24000]],
                "typical_price_range": [21000, 28000]
            }
        }
        result = evaluate_price_deal(flight_data)
        self.assertFalse(result["is_deal"])
        self.assertEqual(result["recommendation"], "WAIT")

    @patch("analyzer.get_local_price_history")
    def test_pass_when_expensive_and_close(self, mock_local_history):
        """Ha az ár drága és már <45 nap van indulásig, javasoljon PASS-t."""
        mock_local_history.return_value = [15000]
        flight_data = {
            "origin": "BUD",
            "destination": "BGY",
            "departure_date": "2026-11-20",
            "return_date": "2026-11-25",
            "price": 29000,
            "days_left": 10,
            "price_insights": {
                "price_history": [[1700000000, 15000], [1700086400, 16000]],
                "typical_price_range": [14000, 19000]
            }
        }
        result = evaluate_price_deal(flight_data)
        self.assertFalse(result["is_deal"])
        self.assertEqual(result["recommendation"], "PASS")

    def test_deterministic_daily_cost(self):
        """Ellenőrzi, hogy az ismert és ismeretlen IATA kódokra helyes EUR értéket ad-e vissza."""
        self.assertEqual(get_deterministic_daily_cost("BGY"), 90)
        self.assertEqual(get_deterministic_daily_cost("ATH"), 65)
        self.assertEqual(get_deterministic_daily_cost("UNKNOWN_CODE"), DEFAULT_DAILY_COST_EUR)

if __name__ == "__main__":
    unittest.main()