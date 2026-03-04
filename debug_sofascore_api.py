import requests

def search_sofascore():
    team_a = "Hamburger SV"
    team_b = "RB Leipzig"
    query = f"{team_a} {team_b}"
    
    url = f"https://api.sofascore.com/api/v1/search/events?q={query}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    response = requests.get(url, headers=headers)
    print(response.status_code)
    try:
        data = response.json()
        results = data.get("results", [])
        if results:
            first = results[0]
            print(f"Found match: {first['customId']}")
            slug = first.get("slug")
            match_id = first.get("id")
            print(f"URL: https://www.sofascore.com/{slug}/{match_id}")
        else:
            print("No results found in JSON.")
    except Exception as e:
        print(f"Error: {e}")
        print(response.text[:200])

if __name__ == "__main__":
    search_sofascore()
