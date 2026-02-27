import sqlite3
import json
from datetime import datetime

DB_NAME = "omnibet.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
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
            match_id INTEGER UNIQUE,
            match_date TEXT,
            teams TEXT,
            full_analysis_json TEXT,
            safe_bet_tip TEXT,
            confidence INTEGER,
            actual_result TEXT,
            is_correct BOOLEAN,
            visible_in_history BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    try:
        cursor.execute('ALTER TABLE predictions ADD COLUMN visible_in_history BOOLEAN DEFAULT 1')
    except sqlite3.OperationalError:
        pass # Column already exists
    
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
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS group_matches (
            group_id INTEGER,
            match_id INTEGER,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (group_id, match_id),
            FOREIGN KEY (group_id) REFERENCES prediction_groups (id) ON DELETE CASCADE,
            FOREIGN KEY (match_id) REFERENCES predictions (match_id) ON DELETE CASCADE
        )
    ''')
    
    conn.commit()
    conn.close()

def save_prediction(data: dict):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO predictions (match_id, match_date, teams, full_analysis_json, safe_bet_tip, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            data.get('match_id'),
            data.get('match_date'),
            data.get('match'),
            json.dumps(data),  # Save the entire prediction object!
            data.get('primary_pick', {}).get('tip', 'Analysis Failed'),
            data.get('primary_pick', {}).get('confidence', 0)
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
        # Total predictions with a known outcome
        cursor.execute('SELECT COUNT(*) FROM predictions WHERE is_correct IS NOT NULL')
        total_resolved = cursor.fetchone()[0]
        
        # Total correct predictions
        cursor.execute('SELECT COUNT(*) FROM predictions WHERE is_correct = 1')
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

def get_cached_prediction(match_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT full_analysis_json, actual_result, is_correct FROM predictions WHERE match_id = ?', (match_id,))
        row = cursor.fetchone()
        if row:
            # We return the exact parsed JSON object that was initially generated
            # so the frontend receives the identical nested format.
            cached_pred = json.loads(row[0]) if row[0] else {}
            # Reattach grading history if any exists
            cached_pred['actual_result'] = row[1]
            cached_pred['is_correct'] = row[2]
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
            full_pred['match_date'] = db_data['match_date']
            full_pred['teams'] = db_data['teams']
            full_pred['actual_result'] = db_data['actual_result']
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
        # Hide predictions that belong to any group
        cursor.execute('''
            UPDATE predictions 
            SET visible_in_history = 0 
            WHERE match_id IN (SELECT match_id FROM group_matches)
        ''')
        # Delete predictions that don't belong to any group
        cursor.execute('''
            DELETE FROM predictions 
            WHERE match_id NOT IN (SELECT match_id FROM group_matches)
        ''')
        conn.commit()
    except Exception as e:
        print(f"Error clearing history: {e}")
    finally:
        conn.close()

def delete_prediction(match_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM predictions WHERE match_id = ?', (match_id,))
        conn.commit()
    except Exception as e:
        print(f"Error deleting prediction {match_id}: {e}")
    finally:
        conn.close()

def restore_to_history(match_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('UPDATE predictions SET visible_in_history = 1 WHERE match_id = ?', (match_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error restoring prediction {match_id}: {e}")
        return False
    finally:
        conn.close()

def update_prediction_result(match_id: int, actual_result: str, is_correct: bool):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            UPDATE predictions 
            SET actual_result = ?, is_correct = ? 
            WHERE match_id = ?
        ''', (actual_result, is_correct, match_id))
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
            SELECT g.id, g.name, g.created_at, COUNT(gm.match_id) as match_count 
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
        cursor.execute('DELETE FROM group_matches WHERE group_id = ?', (group_id,))
        cursor.execute('DELETE FROM prediction_groups WHERE id = ?', (group_id,))
        conn.commit()
    except Exception as e:
        print(f"Error deleting group {group_id}: {e}")
    finally:
        conn.close()

def add_match_to_group(group_id: int, match_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT OR IGNORE INTO group_matches (group_id, match_id) VALUES (?, ?)', (group_id, match_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error adding match {match_id} to group {group_id}: {e}")
        return False
    finally:
        conn.close()

def remove_match_from_group(group_id: int, match_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM group_matches WHERE group_id = ? AND match_id = ?', (group_id, match_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error removing match {match_id} from group {group_id}: {e}")
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
            JOIN group_matches gm ON p.match_id = gm.match_id
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

# Initialize on module load (simple for now)
init_db()
