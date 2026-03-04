from src.services.sports_api import resolve_sofascore_match_id

id = resolve_sofascore_match_id("Everton", "Burnley")
print("FOUND ID:", id)
