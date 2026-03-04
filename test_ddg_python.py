from duckduckgo_search import DDGS
import re 
import requests

query = "site:sofascore.com/football/match Everton Burnley"

try:
    with DDGS() as ddgs:
        results = [r for r in ddgs.text(query, max_results=3)]
        
        target_url = None
        for r in results:
            if 'sofascore.com/football/match' in r['href']:
                target_url = r['href']
                break
                
        print("Found URL:", target_url)
        
        if target_url:
            # But the URL doesn't have the ID anymore. We must extract the ID from the HTML or page.
            # And we know Cloudflare blocks requests.get(). 
            # Oh wait, we CAN get the ID from Bing search result snippets or Duckduckgo result snippets!
            # Let's check the snippets themselves.
            print("Snippets:")
            for r in results:
                print(r['body'])
except ImportError:
    print("pip install duckduckgo-search")
except Exception as e:
    print(e)
