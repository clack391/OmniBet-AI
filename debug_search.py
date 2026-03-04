from googlesearch import search
team_a = "Hamburger SV"
team_b = "RB Leipzig"
query = f"sofascore {team_a} {team_b}"
print(f"Query: {query}")
try:
    for url in search(query, num_results=5):
        print(f"Found snippet: {url}")
except Exception as e:
    print(f"Error: {e}")
