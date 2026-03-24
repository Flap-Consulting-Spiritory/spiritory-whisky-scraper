import requests

WHISKYHUNTER_BASE_URL = "https://whiskyhunter.net/api"

def fetch_historical_auctions(distillery: str) -> list[dict]:
    """
    Fetches historical auction data from WhiskyHunter API.
    A simple mapping logic is applied here, substituting spaces for dashes.
    """
    try:
        slug = str(distillery).lower().strip().replace(" ", "-")
        # According to WhiskyHunter API: /api/auctions_data/{distillery_slug}
        # returns historical stats for a distillery
        url = f"{WHISKYHUNTER_BASE_URL}/auctions_data/{slug}/"
        
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            results = []
            # Extract standard price (we'll just use the volume or a specific median price from their data structure)
            # The API returns points for each month for the distillery
            for item in data:
                # E.g. {"dt": "2023-01", "winning_bid_max": 500, "winning_bid_mean": 120...}
                price_val = item.get("winning_bid_mean", 0)
                if price_val > 0:
                    results.append({
                        "price": price_val,
                        "currency": "GBP", # WhiskyHunter is typically in GBP
                        "recorded_at": f"{item.get('dt')}-01T00:00:00Z"
                    })
            return results
        else:
            print(f"[WhiskyHunter] Non-200 status for distillery {distillery}: {response.status_code}")
            return []
    except Exception as e:
        print(f"[WhiskyHunter] Error fetching historical auctions for {distillery}: {e}")
        return []
