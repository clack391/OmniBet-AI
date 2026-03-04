from apify_client import ApifyClient
import os
import re
from dotenv import load_dotenv

load_dotenv()
apify_token = os.getenv("APIFY_API_TOKEN")
client = ApifyClient(apify_token)

# Run a quick web-scraper on the sofascore URL to get the HTML
url = "https://www.sofascore.com/football/match/everton-burnley/gsY"
run_input = {
    "startUrls": [{"url": url}],
    "pageFunction": """
        async function pageFunction(context) {
            const html = await context.page.content();
            return { html: html.substring(0, 15000) }; // return the first 15k chars
        }
    """,
    "proxyConfiguration": {"useApifyProxy": True}
}

print("Running scraper on", url)
run = client.actor("apify/puppeteer-scraper").call(run_input=run_input)

for item in client.dataset(run["defaultDatasetId"]).iterate_items():
    html = item.get("html", "")
    print("Found HTML len:", len(html))
    match = re.search(r'"eventId":(\d+)', html)
    if not match:
        match = re.search(r'"id":(\d+),"status"', html)
    if not match:
        match = re.search(r'android-app://com.sofascore.results/https/www.sofascore.com/event/(\d+)', html)
    if match:
        print("FOUND ID:", match.group(1))
    else:
        print("NO MATCH in HTML")
