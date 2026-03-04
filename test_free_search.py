import requests
import urllib.parse
from bs4 import BeautifulSoup
import re

def search_duckduckgo(query):
    # DuckDuckGo HTML version doesn't block scrapers as aggressively as Google
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    
    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            for a in soup.find_all('a', class_='result__snippet'):
                href = a.get('href')
                if href and 'sofascore.com/football/match' in href:
                    # Duckduckgo redirects look like: //duckduckgo.com/l/?uddg=https://www.sofascore...
                    actual_url = urllib.parse.unquote(href.split('uddg=')[1].split('&')[0])
                    return actual_url
    except Exception as e:
        print(f"Search error: {e}")
    return None

def fetch_sofascore_id(url):
    # Now we need to get the ID. Sofascore blocks direct requests to the match page, 
    # but their API endpoint for next-matches or H2H might be open or we can try a different trick.
    pass

url = search_duckduckgo("site:sofascore.com/football/match Everton Burnley")
print("Found URL via DDG:", url)
