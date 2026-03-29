import sqlite3
import json
from datetime import datetime
import unicodedata
import re

DB_NAME = "omnibet.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password_hash TEXT,
            role TEXT DEFAULT 'user'
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER,
            booking_code TEXT,
            selection TEXT,
            match_date TEXT,
            teams TEXT,
            full_analysis_json TEXT,
            safe_bet_tip TEXT,
            confidence INTEGER,
            home_logo TEXT,
            away_logo TEXT,
            actual_result TEXT,
            status TEXT,
            is_correct BOOLEAN,
            visible_in_history BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(match_id, booking_code)
        )
    ''')
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_predictions_history
        ON predictions (visible_in_history, match_date DESC)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_predictions_match_id
        ON predictions (match_id)
    """)

    # --- MIGRATION BLOCK: predictions ---
    try:
        cursor.execute('ALTER TABLE predictions ADD COLUMN booking_code TEXT')
    except sqlite3.OperationalError: pass
    try: 
        cursor.execute('ALTER TABLE predictions ADD COLUMN selection TEXT')
    except sqlite3.OperationalError: pass

    # Check if we need to remove the UNIQUE(match_id) constraint
    cursor.execute("PRAGMA index_list('predictions')")
    indices = cursor.fetchall()
    needs_pred_mig = False
    for idx in indices:
        if idx[2] == 1: # Unique
            cursor.execute(f"PRAGMA index_info('{idx[1]}')")
            cols = [c[2] for c in cursor.fetchall()]
            if len(cols) == 1 and cols[0] == 'match_id':
                needs_pred_mig = True
                break
    
    if needs_pred_mig:
        print("🛠️ Migrating predictions: Transitioning to per-slip audit storage...")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS predictions_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER,
                booking_code TEXT,
                selection TEXT,
                match_date TEXT,
                teams TEXT,
                full_analysis_json TEXT,
                safe_bet_tip TEXT,
                confidence INTEGER,
                home_logo TEXT,
                away_logo TEXT,
                actual_result TEXT,
                status TEXT,
                is_correct BOOLEAN,
                visible_in_history BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(match_id, booking_code)
            )
        ''')
        cursor.execute("INSERT INTO predictions_new (id, match_id, booking_code, selection, match_date, teams, full_analysis_json, safe_bet_tip, confidence, home_logo, away_logo, actual_result, status, is_correct, visible_in_history, created_at) SELECT id, match_id, booking_code, selection, match_date, teams, full_analysis_json, safe_bet_tip, confidence, home_logo, away_logo, actual_result, status, is_correct, visible_in_history, created_at FROM predictions")
        cursor.execute("DROP TABLE predictions")
        cursor.execute("ALTER TABLE predictions_new RENAME TO predictions")
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_fixtures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE,
            fixtures_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ai_best_picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            accumulator_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS prediction_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # --- MIGRATION BLOCK: group_matches ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS group_matches (
            group_id INTEGER,
            prediction_id INTEGER,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (group_id, prediction_id),
            FOREIGN KEY (group_id) REFERENCES prediction_groups (id) ON DELETE CASCADE,
            FOREIGN KEY (prediction_id) REFERENCES predictions (id) ON DELETE CASCADE
        )
    ''')

    # Detect if we are on the old schema (match_id instead of prediction_id)
    cursor.execute("PRAGMA table_info(group_matches)")
    gm_cols = [r[1] for r in cursor.fetchall()]
    if "match_id" in gm_cols and "prediction_id" not in gm_cols:
         print("🛠️ Migrating group_matches: Transitioning to ID-based linking...")
         cursor.execute("ALTER TABLE group_matches ADD COLUMN prediction_id INTEGER")
         # Link existing matches to the first available prediction ID
         cursor.execute("UPDATE group_matches SET prediction_id = (SELECT id FROM predictions WHERE predictions.match_id = group_matches.match_id LIMIT 1)")
         # Recreate group_matches to set PK correctly
         cursor.execute("ALTER TABLE group_matches RENAME TO group_matches_old")
         cursor.execute('''
            CREATE TABLE group_matches (
                group_id INTEGER,
                prediction_id INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (group_id, prediction_id),
                FOREIGN KEY (group_id) REFERENCES prediction_groups (id) ON DELETE CASCADE,
                FOREIGN KEY (prediction_id) REFERENCES predictions (id) ON DELETE CASCADE
            )
        ''')
         cursor.execute("INSERT INTO group_matches (group_id, prediction_id, added_at) SELECT group_id, prediction_id, added_at FROM group_matches_old WHERE prediction_id IS NOT NULL")
         cursor.execute("DROP TABLE group_matches_old")
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            job_id      TEXT PRIMARY KEY,
            match_id    INTEGER,
            status      TEXT DEFAULT 'PENDING',
            result_json TEXT,
            error_msg   TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            updated_at  TEXT DEFAULT (datetime('now'))
        )
    ''')

    conn.commit()
    conn.close()

def save_prediction(data: dict):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO predictions (match_id, booking_code, selection, match_date, teams, full_analysis_json, safe_bet_tip, confidence, home_logo, away_logo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get('match_id'),
            data.get('booking_code') or '',
            data.get('user_selected_bet') or '',
            data.get('match_date'),
            data.get('match'),
            json.dumps(data),
            data.get('supreme_court', {}).get('Arbiter_Safe_Pick', {}).get('tip') or 
            data.get('supreme_court', {}).get('primary_safe_pick', {}).get('tip') or 
            data.get('primary_pick', {}).get('tip') or 
            data.get('safe_bet_tip', 'Analysis Failed'),
            data.get('supreme_court', {}).get('Arbiter_Safe_Pick', {}).get('confidence') or 
            data.get('supreme_court', {}).get('primary_safe_pick', {}).get('confidence') or 
            data.get('primary_pick', {}).get('confidence') or 
            data.get('confidence', 0),
            data.get('home_logo'),
            data.get('away_logo')
        ))
        conn.commit()
    except Exception as e:
        print(f"Error saving prediction: {e}")
    finally:
        conn.close()

def get_accuracy_stats():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    try:
        # Total predictions with a known outcome (ignoring refunds)
        cursor.execute('SELECT COUNT(*) FROM predictions WHERE is_correct IS NOT NULL AND is_correct != "refund"')
        total_resolved = cursor.fetchone()[0]
        
        # Total correct predictions
        cursor.execute('SELECT COUNT(*) FROM predictions WHERE is_correct = 1 OR is_correct = "true"')
        total_correct = cursor.fetchone()[0]
        
        win_rate = 0
        if total_resolved > 0:
            win_rate = round((total_correct / total_resolved) * 100, 2)
            
        return {
            "total_resolved": total_resolved,
            "total_correct": total_correct,
            "win_rate": win_rate
        }
    finally:
        conn.close()

def get_cached_prediction(match_id: int, booking_code: str = None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        if booking_code:
            cursor.execute('SELECT full_analysis_json, actual_result, status, is_correct, id FROM predictions WHERE match_id = ? AND booking_code = ?', (match_id, booking_code))
        else:
            # If no code provided, get the most recent non-audit or any recent prediction
            cursor.execute('SELECT full_analysis_json, actual_result, status, is_correct, id FROM predictions WHERE match_id = ? ORDER BY created_at DESC LIMIT 1', (match_id,))
        
        row = cursor.fetchone()
        if row:
            cached_pred = json.loads(row[0]) if row[0] else {}
            # Reattach grading history if any exists
            cached_pred['id'] = row[4]
            cached_pred['actual_result'] = row[1]
            cached_pred['status'] = row[2]
            cached_pred['is_correct'] = row[3]
            return cached_pred
        return None
    except Exception as e:
        print(f"Error reading prediction cache: {e}")
        return None
    finally:
        conn.close()

def get_all_predictions():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM predictions WHERE visible_in_history = 1 ORDER BY match_date DESC')
        rows = cursor.fetchall()
        results = []
        for row in rows:
            db_data = dict(row)
            # The saved JSON contains the fully hydrated prediction card config
            full_pred = json.loads(db_data['full_analysis_json']) if db_data['full_analysis_json'] else {}
            
            # Decorate the full prediction with DB-specific metadata used by HistoryTab
            full_pred['id'] = db_data['id']
            full_pred['match_id'] = db_data['match_id']
            full_pred['match_date'] = db_data['match_date']
            full_pred['teams'] = db_data['teams']
            full_pred['home_logo'] = db_data['home_logo'] or full_pred.get('home_logo')
            full_pred['away_logo'] = db_data['away_logo'] or full_pred.get('away_logo')
            full_pred['actual_result'] = db_data['actual_result']
            full_pred['status'] = db_data['status']
            full_pred['is_correct'] = db_data['is_correct']
            
            # Safety: in case primary_pick isn't neatly in full_pred text
            if 'primary_pick' not in full_pred:
                full_pred['primary_pick'] = {
                    "tip": db_data['safe_bet_tip'],
                    "confidence": db_data['confidence']
                }
            if 'alternative_pick' not in full_pred:
                 full_pred['alternative_pick'] = None
                
            results.append(full_pred)
        return results
    except Exception as e:
        print(f"Error fetching history: {e}")
        return []
    finally:
        conn.close()

def clear_predictions():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        # User requested a strict hard delete for all predictions
        cursor.execute('DELETE FROM group_matches')
        cursor.execute('DELETE FROM ai_best_picks')
        cursor.execute('DELETE FROM predictions')
        conn.commit()
        conn.commit()
    except Exception as e:
        print(f"Error clearing history: {e}")
    finally:
        conn.close()

def delete_prediction(prediction_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        # User requested a strict hard delete across all associations
        cursor.execute('DELETE FROM group_matches WHERE prediction_id = ?', (prediction_id,))
        cursor.execute('DELETE FROM predictions WHERE id = ?', (prediction_id,))
        conn.commit()
    except Exception as e:
        print(f"Error deleting prediction {prediction_id}: {e}")
    finally:
        conn.close()

def restore_to_history(prediction_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('UPDATE predictions SET visible_in_history = 1 WHERE id = ?', (prediction_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error restoring prediction {prediction_id}: {e}")
        return False
    finally:
        conn.close()

def update_prediction_result(match_id: int, actual_result: str, status: str, is_correct: bool):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            UPDATE predictions 
            SET actual_result = ?, status = ?, is_correct = ? 
            WHERE match_id = ?
        ''', (actual_result, status, is_correct, match_id))
        conn.commit()
    except Exception as e:
        print(f"Error updating result: {e}")
    finally:
        conn.close()

def get_cached_fixtures(date_str: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT fixtures_json FROM daily_fixtures WHERE date = ?', (date_str,))
        row = cursor.fetchone()
        if row:
            return json.loads(row[0])
        return None
    except Exception as e:
        print(f"Error reading cache: {e}")
        return None
    finally:
        conn.close()

def save_fixtures_cache(date_str: str, data: dict):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        # Using REPLACE because 'date' must be UNIQUE in schema
        cursor.execute('''
            REPLACE INTO daily_fixtures (date, fixtures_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (date_str, json.dumps(data)))
        conn.commit()
    except Exception as e:
        print(f"Error saving cache: {e}")
    finally:
        conn.close()

def save_best_picks(data: dict):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO ai_best_picks (accumulator_json)
            VALUES (?)
        ''', (json.dumps(data),))
        conn.commit()
    except Exception as e:
        print(f"Error saving accumulator: {e}")
    finally:
        conn.close()

def get_best_picks():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        # Get the most recent one
        cursor.execute('SELECT accumulator_json, created_at FROM ai_best_picks ORDER BY created_at DESC LIMIT 1')
        row = cursor.fetchone()
        if row:
            data = json.loads(row[0])
            data['created_at'] = row[1]
            return data
        return None
    except Exception as e:
        print(f"Error reading accumulator: {e}")
        return None
    finally:
        conn.close()

def clear_best_picks():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM ai_best_picks')
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='ai_best_picks'")
        conn.commit()
    except Exception as e:
        print(f"Error clearing accumulators: {e}")
    finally:
        conn.close()

# --- Group / Folder Functions ---

def create_group(name: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO prediction_groups (name) VALUES (?)', (name,))
        conn.commit()
        return {"id": cursor.lastrowid, "name": name}
    except sqlite3.IntegrityError:
        return {"error": "Group already exists"}
    except Exception as e:
        print(f"Error creating group: {e}")
        return {"error": str(e)}
    finally:
        conn.close()

def get_groups():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT g.id, g.name, g.created_at, COUNT(gm.prediction_id) as match_count 
            FROM prediction_groups g
            LEFT JOIN group_matches gm ON g.id = gm.group_id
            GROUP BY g.id
            ORDER BY g.created_at DESC
        ''')
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"Error fetching groups: {e}")
        return []
    finally:
        conn.close()

def delete_group(group_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        # 1. Remove the link between matches and this group first
        # We do NOT delete the predictions themselves, as they belong to the main history.
        cursor.execute('DELETE FROM group_matches WHERE group_id = ?', (group_id,))
        
        # 2. Delete the group definition
        cursor.execute('DELETE FROM prediction_groups WHERE id = ?', (group_id,))
        
        conn.commit()
    except Exception as e:
        print(f"Error deleting group {group_id}: {e}")
        conn.rollback()
        raise e # Re-raise so the API endpoint knows it failed
    finally:
        conn.close()

def add_match_to_group(group_id: int, prediction_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT OR IGNORE INTO group_matches (group_id, prediction_id) VALUES (?, ?)', (group_id, prediction_id))
        # Hide the match from the main Prediction History Tab automatically
        cursor.execute('UPDATE predictions SET visible_in_history = 0 WHERE id = ?', (prediction_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error adding prediction {prediction_id} to group {group_id}: {e}")
        return False
    finally:
        conn.close()

def remove_match_from_group(group_id: int, prediction_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        # Soft unarchive: remove from the specific folder but restore visibility in the main history feed
        cursor.execute('DELETE FROM group_matches WHERE group_id = ? AND prediction_id = ?', (group_id, prediction_id))
        cursor.execute('UPDATE predictions SET visible_in_history = 1 WHERE id = ?', (prediction_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error removing prediction {prediction_id} from group {group_id}: {e}")
        return False
    finally:
        conn.close()

def get_matches_by_group(group_id: int):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT p.* FROM predictions p
            JOIN group_matches gm ON p.id = gm.prediction_id
            WHERE gm.group_id = ?
            ORDER BY gm.added_at DESC
        ''', (group_id,))
        rows = cursor.fetchall()
        results = []
        for row in rows:
            db_data = dict(row)
            full_pred = json.loads(db_data['full_analysis_json']) if db_data['full_analysis_json'] else {}
            full_pred['id'] = db_data['id']
            full_pred['match_date'] = db_data['match_date']
            full_pred['teams'] = db_data['teams']
            full_pred['home_logo'] = db_data['home_logo'] or full_pred.get('home_logo')
            full_pred['away_logo'] = db_data['away_logo'] or full_pred.get('away_logo')
            full_pred['actual_result'] = db_data['actual_result']
            full_pred['is_correct'] = db_data['is_correct']
            
            if 'primary_pick' not in full_pred:
                full_pred['primary_pick'] = {
                    "tip": db_data['safe_bet_tip'],
                    "confidence": db_data['confidence']
                }
            if 'alternative_pick' not in full_pred:
                 full_pred['alternative_pick'] = None
                 
            results.append(full_pred)
        return results
    except Exception as e:
        print(f"Error fetching matches for group {group_id}: {e}")
        return []
    finally:
        conn.close()

# --- Match Searching Cross Date ---
import re

def _clean_team_name(name: str) -> set:
    if not name: return set()
    name = name.lower()
    
    # Norway/Denmark explicit mapping BEFORE stripping
    name = name.replace('ø', 'oe').replace('æ', 'ae')
    
    # Universal Normalization: Removes ALL accents/diacritics (e.g., á -> a, ñ -> n, ç -> c)
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('utf-8')
    
    # Strip everything except lowercase and spaces before replacements
    name = re.sub(r'[^a-z0-9\s]', ' ', name)
    
    # Handle common translations/abbreviations
    replacements = {
        "munchen": "bayern",
        "munich": "bayern",
        "mgladbach": "monchengladbach",
        "gladb": "monchengladbach",
        "utd": "united",
        "man": "manchester",
        "man u": "manchester united",
        "man city": "manchester city",
        "atletico madrid": "atletico",
        "psg": "paris saint germain",
        "wolves": "wolverhampton",
        "spurs": "tottenham",
        "intl": "internacional",
        "ahli": "al ahli",
        "ittihad": "al ittihad",
        "stade": "",
        "athletic": "",
        "club": "",
        "clube": "",
        "deportivo": "",
        "depor": "",
        "cp": "sporting",
        "lisbon": "sporting",
        "braga": "sporting braga",
        "amateur": "",
        "u19": "",
        "u21": "",
        "u23": "",
        "reserves": ""
    }
    for old, new in replacements.items():
        name = re.sub(rf'\b{old}\b', new, name)

    # Remove standard noise words
    noise = ['fc', 'ca', 'sc', 'cf', 'de', 'afc', 'as', 'fk', 'rio', 'v', 'vs', 'al', 'stade', 'club', 'clube', 'desportivo']
    for word in noise:
        name = re.sub(rf'\b{word}\b', '', name)
        
    # Extract only alphanumeric words with length >= 2
    words = set(re.findall(r'[a-z0-9]{2,}', name))
    return words

def find_fixtures_cross_date(parsed_matches: list):
    """
    Given a list of {"home_team": "Team A", "away_team": "Team B"}
    Looks through ALL daily_fixtures JSON payloads in the database.
    Returns the enriched matches with their actual `match_id` and `match_date`.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    hydrated_matches = []
    unmatched_names = []
    
    try:
        provider = get_app_setting("primary_provider", "football-data")
        
        cursor.execute("SELECT date, fixtures_json FROM daily_fixtures")
        rows = cursor.fetchall()
        
        # Load all cached fixtures into a single massive array for quick searching
        all_cached_fixtures = []
        for row in rows:
            date_str = row[0]
            
            # RELAXED: We search across ALL cached fixtures regardless of provider.
            # This allows a SportyBet code to match against ANY data we have stored.
            # We still tag the date_str to maintain context.

            if row[1]:
                raw_json = json.loads(row[1])
                
                # Depending on the active Data Provider (SofaScore vs Football-Data),
                # the root JSON might be a list, or it might be wrapped in a dict.
                fixtures_list = []
                if isinstance(raw_json, dict):
                    fixtures_list = raw_json.get('matches', []) or raw_json.get('events', [])
                elif isinstance(raw_json, list):
                    fixtures_list = raw_json
                    
                for f in fixtures_list:
                    if isinstance(f, dict):
                        f['_omni_date'] = date_str # Tag the date onto the object
                        
                all_cached_fixtures.extend(fixtures_list)
                
        # Now fuzzy match each parsed match against this massive array
        for pm in parsed_matches:
            targetHomeWords = _clean_team_name(pm.get('home_team', ''))
            targetAwayWords = _clean_team_name(pm.get('away_team', ''))
            
            if not targetHomeWords or not targetAwayWords:
                unmatched_names.append(f"{pm.get('home_team')} vs {pm.get('away_team')} (Incomplete Names)")
                continue

            found = False
            best_match = None
            max_score = 0
            
            for f in all_cached_fixtures:
                fHomeWords = _clean_team_name(f.get('homeTeam', {}).get('name', ''))
                fAwayWords = _clean_team_name(f.get('awayTeam', {}).get('name', ''))
                
                # Scoring Match:
                # 1. Home word in Home fixture? (Direct)
                # 2. Away word in Away fixture? (Direct)
                # 3. Home word in Away fixture? (Inverse/Swap detection)
                # 4. Away word in Home fixture? (Inverse/Swap detection)
                
                home_direct = len(targetHomeWords & fHomeWords)
                away_direct = len(targetAwayWords & fAwayWords)
                home_swap = len(targetHomeWords & fAwayWords)
                away_swap = len(targetAwayWords & fHomeWords)
                
                is_direct = home_direct > 0 and away_direct > 0
                is_swapped = home_swap > 0 and away_swap > 0
                
                # Calculate a total confidence score
                # Direct matches are significantly more likely to be correct than swaps.
                # We weight direct matches higher and require a threshold.
                score = 0
                if is_direct:
                    score = (home_direct + away_direct) * 2  # Double weight for direct
                elif is_swapped:
                    score = (home_swap + away_swap)          # Normal weight for swap
                
                if score > max_score:
                    max_score = score
                    best_match = f
            
            # We need a minimum threshold to be confident
            # 2 is the floor (e.g., 1 word match per team in a swap, or 1/2 match in a direct)
            if best_match and max_score >= 2:
                print(f"✅ Match Found: '{pm.get('home_team')} vs {pm.get('away_team')}' -> '{best_match.get('homeTeam',{}).get('name')} vs {best_match.get('awayTeam',{}).get('name')}' (Score: {max_score})")
                # Pass the user's original bet to the frontend
                if 'user_selected_bet' in pm:
                    best_match['_user_selected_bet'] = pm['user_selected_bet']
                    
                hydrated_matches.append(best_match)
                found = True
            
            if not found:
                print(f"❌ Match Failed: '{pm.get('home_team')} vs {pm.get('away_team')}'")
                unmatched_names.append(f"{pm.get('home_team')} vs {pm.get('away_team')}")
                
        # Deduplicate unmatched names while preserving order
        unique_unmatched = list(dict.fromkeys(unmatched_names))
        return {"matched": hydrated_matches, "unmatched": unique_unmatched}
        
    except Exception as e:
        print(f"Error cross-searching dates: {e}")
        return {"matched": [], "unmatched": []}
    finally:
        conn.close()

# --- App Settings Functions ---

def get_app_setting(key: str, default_value: str = None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT value FROM app_settings WHERE key = ?', (key,))
        row = cursor.fetchone()
        if row:
            return row[0]
        return default_value
    except Exception as e:
        print(f"Error fetching setting {key}: {e}")
        return default_value
    finally:
        conn.close()

def set_app_setting(key: str, value: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO app_settings (key, value)
            VALUES (?, ?)
        ''', (key, value))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error setting {key}: {e}")
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Jobs table — async task tracking
# ---------------------------------------------------------------------------

def create_job(job_id: str, match_id: int):
    conn = sqlite3.connect(DB_NAME)
    try:
        conn.execute(
            "INSERT INTO jobs (job_id, match_id, status) VALUES (?, ?, 'PENDING')",
            (job_id, match_id)
        )
        conn.commit()
    finally:
        conn.close()


def update_job_status(job_id: str, status: str):
    conn = sqlite3.connect(DB_NAME)
    try:
        conn.execute(
            "UPDATE jobs SET status=?, updated_at=datetime('now') WHERE job_id=?",
            (status, job_id)
        )
        conn.commit()
    finally:
        conn.close()


def save_job_result(job_id: str, result: dict):
    conn = sqlite3.connect(DB_NAME)
    try:
        conn.execute(
            "UPDATE jobs SET status='COMPLETED', result_json=?, updated_at=datetime('now') WHERE job_id=?",
            (json.dumps(result), job_id)
        )
        conn.commit()
    finally:
        conn.close()


def fail_job(job_id: str, error_msg: str):
    conn = sqlite3.connect(DB_NAME)
    try:
        conn.execute(
            "UPDATE jobs SET status='FAILED', error_msg=?, updated_at=datetime('now') WHERE job_id=?",
            (error_msg, job_id)
        )
        conn.commit()
    finally:
        conn.close()


def get_job(job_id: str):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM jobs WHERE job_id=?", (job_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("result_json"):
            try:
                d["result"] = json.loads(d["result_json"])
            except Exception:
                d["result"] = None
        else:
            d["result"] = None
        return d
    finally:
        conn.close()

# Initialize on module load (simple for now)
init_db()
