from apify_client import ApifyClient
import os
from dotenv import load_dotenv

load_dotenv()

apify_token = os.getenv("APIFY_API_TOKEN")
client = ApifyClient(apify_token)
query = f"site:sofascore.com/football/match Everton Burnley"

run_input = {
    "queries": query,
    "resultsPerPage": 3,
    "maxPagesPerQuery": 1,
    "languageCode": "en"
}

run = client.actor("apify/google-search-scraper").call(run_input=run_input)

for item in client.dataset(run["defaultDatasetId"]).iterate_items():
    organic = item.get("organicResults", [])
    for res in organic:
        print("FOUND URL:", res.get("url", ""))
