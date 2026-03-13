import json
import os

PREFS_FILE = "data/user_prefs.json"

def get_user_preference(chat_id):
    """
    Retrieves the prediction delivery preference for a specific user.
    Defaults to 'text'.
    """
    if not os.path.exists(PREFS_FILE):
        return 'text'
    try:
        with open(PREFS_FILE, 'r') as f:
            prefs = json.load(f)
            return prefs.get(str(chat_id), 'text')
    except Exception:
        return 'text'

def set_user_preference(chat_id, mode):
    """
    Saves the prediction delivery preference (text or image) for a user.
    """
    prefs = {}
    if os.path.exists(PREFS_FILE):
        try:
            with open(PREFS_FILE, 'r') as f:
                prefs = json.load(f)
        except Exception:
            pass
    
    prefs[str(chat_id)] = mode
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(PREFS_FILE), exist_ok=True)
    
    with open(PREFS_FILE, 'w') as f:
        json.dump(prefs, f, indent=4)
