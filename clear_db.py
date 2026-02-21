#!/usr/bin/env python3
import sqlite3
import os

DB_NAME = "omnibet.db"

def clear_all_predictions():
    """
    Utility script to completely wipe the `predictions` table
    from the SQLite database, effectively resetting the History tab.
    """
    if not os.path.exists(DB_NAME):
        print(f"Database {DB_NAME} not found. Nothing to clear.")
        return

    print(f"Connecting to {DB_NAME}...")
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Checking how many records are about to be deleted
        cursor.execute("SELECT COUNT(*) FROM predictions")
        count = cursor.fetchone()[0]
        
        if count == 0:
            print("The predictions table is already empty.")
        else:
            confirm = input(f"WARNING: This will delete all {count} saved AI predictions. Are you sure? (y/n): ")
            if confirm.lower() == 'y':
                cursor.execute("DELETE FROM predictions")
                # Reset the autoincrement ID counter
                cursor.execute("DELETE FROM sqlite_sequence WHERE name='predictions'")
                conn.commit()
                print("✅ Successfully cleared all past predictions and reset ID sequence.")
            else:
                print("Operation cancelled. Data is safe.")
                
    except Exception as e:
        print(f"❌ Error clearing database: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

if __name__ == "__main__":
    print("--- OmniBet AI Database Wiping Utility ---")
    clear_all_predictions()
