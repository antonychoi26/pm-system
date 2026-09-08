"""
Migration: 多人指派工作項目

變更內容：
  1. 建立 task_todo_assignees 關聯表（多對多）
  2. 將 task_todos.assignee_id 的現有資料遷移至新表
  3. 移除 task_todos.assignee_id 欄位（SQLite 不支援 DROP COLUMN，
     改以重建資料表方式處理）

在 PythonAnywhere 執行一次：
  cd ~/pm-system && python migrate_add_todo_assignee.py
"""
import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, 'pm_system.db')


def run():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")   # 暫停 FK 檢查，允許重建
    cur = conn.cursor()

    # ── 1. 建立 task_todo_assignees（若尚未存在）──────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS task_todo_assignees (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            todo_id  INTEGER NOT NULL REFERENCES task_todos(id),
            user_id  INTEGER NOT NULL REFERENCES users(id),
            UNIQUE(todo_id, user_id)
        )
    """)
    print("task_todo_assignees 表已就緒。")

    # ── 2. 從舊欄位遷移資料 ───────────────────────────────────────────────────
    cur.execute("PRAGMA table_info(task_todos)")
    cols = [row[1] for row in cur.fetchall()]

    if 'assignee_id' in cols:
        print("正在遷移舊 assignee_id 資料…")
        cur.execute("""
            INSERT OR IGNORE INTO task_todo_assignees (todo_id, user_id)
            SELECT id, assignee_id
            FROM   task_todos
            WHERE  assignee_id IS NOT NULL
        """)
        migrated = cur.rowcount
        print(f"  已遷移 {migrated} 筆指派記錄。")

        # ── 3. 重建 task_todos（移除 assignee_id 欄位）────────────────────────
        print("正在重建 task_todos 表（移除 assignee_id 欄位）…")

        # 取得現有欄位清單（排除 assignee_id）
        cur.execute("PRAGMA table_info(task_todos)")
        all_cols = cur.fetchall()
        keep_cols = [c for c in all_cols if c[1] != 'assignee_id']
        col_names = ', '.join(c[1] for c in keep_cols)

        # 建立暫存表
        cur.execute("ALTER TABLE task_todos RENAME TO _task_todos_old")

        cur.execute(f"""
            CREATE TABLE task_todos (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id       INTEGER NOT NULL REFERENCES tasks(id),
                title         TEXT    NOT NULL,
                note          TEXT,
                sort_order    INTEGER DEFAULT 0,
                is_done       INTEGER DEFAULT 0,
                priority      TEXT    DEFAULT 'normal',
                due_date      DATE,
                done_at       DATETIME,
                done_by_id    INTEGER REFERENCES users(id),
                created_by_id INTEGER REFERENCES users(id),
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute(f"""
            INSERT INTO task_todos ({col_names})
            SELECT {col_names} FROM _task_todos_old
        """)

        cur.execute("DROP TABLE _task_todos_old")
        print("  task_todos 重建完成。")
    else:
        print("assignee_id 欄位不存在（可能已遷移過）— 跳過。")

    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()
    print("遷移完成 ✓")


if __name__ == '__main__':
    run()
