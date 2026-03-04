from src.services.sports_api import get_sofascore_match_stats, resolve_sofascore_match_id
import json

match_id = resolve_sofascore_match_id('Arsenal', 'Chelsea')
if match_id:
    df, advanced_stats = get_sofascore_match_stats(match_id)
    if advanced_stats:
        print(json.dumps(advanced_stats, indent=2))
    else:
        print("Failed building stats.")
else:
    print("Failed resolving ID.")
