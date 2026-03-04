from duckduckgo_search import DDGS

team_a = "Hamburger SV"
team_b = "RB Leipzig"
query = f"site:sofascore.com/football/match {team_a} vs {team_b}"
try:
    with DDGS() as ddgs:
        results = [r for r in ddgs.text(query, max_results=5)]
        for r in results:
            if "sofascore.com/football/match" in r['href']:
                print(f"FOUND: {r['href']}")
except Exception as e:
    print(f"DDG Error: {e}")
