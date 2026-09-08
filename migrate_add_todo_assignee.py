"""
Migration: Add assignee_id column to task_todos table
Run once on PythonAnywhere:
  cd ~/pm-system && python migrate_add_todo_assignee.py
"""
import sqlite3
import os

# Adjust this path if your DB is elsewhere
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, 'pm_system.db')

def run():
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    # Check if column already exists
    cur.execute("PRAGMA table_info(task_todos)")
    cols = [row[1] for row in cur.fetchall()]

    if 'assignee_id' not in cols:
        print("Adding assignee_id column to task_todos …")
        cur.execute("""
            ALTER TABLE task_todos
            ADD COLUMN assignee_id INTEGER REFERENCES users(id)
        """)
        conn.commit()
        print("Done.")
    else:
        print("Column assignee_id already exists — skipping.")

    conn.close()

if __name__ == '__main__':
    run()
