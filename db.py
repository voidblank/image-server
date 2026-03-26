import sqlite3

DB = "data.db"


def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        img BLOB,
        publish TEXT,
        author TEXT,
        author_tag TEXT,
        simple_title TEXT,
        remarks TEXT,
        is_exists INTEGER DEFAULT 1,
        is_deleted BOOLEAN DEFAULT 0,
        img_compressed BLOB
    )
    """)
    # conn.execute("ALTER TABLE items ADD COLUMN is_deleted BOOLEAN DEFAULT 0")

    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_items_title ON items(title)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_simple_title ON items(simple_title)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_publish ON items(publish)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_author_tag ON items(author_tag)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_exists ON items(is_exists)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_deleted ON items(is_deleted)")

    # 自动添加img_compressed字段（向后兼容）
    try:
        conn.execute("ALTER TABLE items ADD COLUMN img_compressed BLOB")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE items ADD COLUMN is_deleted BOOLEAN DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    conn.execute("""
    CREATE TABLE IF NOT EXISTS tags(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS item_tags(
        item_id INTEGER,
        tag_id INTEGER,
        PRIMARY KEY(item_id,tag_id)
    )
    """)

    conn.commit()
    conn.close()


def set_tags(conn, item_id, tag_names):
    cur = conn.cursor()

    cur.execute("DELETE FROM item_tags WHERE item_id=?", (item_id,))

    for name in tag_names:

        name = name.strip()

        if not name:
            continue

        cur.execute(
            "INSERT OR IGNORE INTO tags(name) VALUES(?)",
            (name,)
        )

        cur.execute(
            "SELECT id FROM tags WHERE name=?",
            (name,)
        )

        tag_id = cur.fetchone()["id"]

        cur.execute(
            "INSERT OR IGNORE INTO item_tags(item_id,tag_id) VALUES(?,?)",
            (item_id, tag_id)
        )


def get_tags(conn, item_id):
    cur = conn.cursor()

    cur.execute("""
    SELECT t.name
    FROM tags t
    JOIN item_tags it ON t.id=it.tag_id
    WHERE it.item_id=?
    """, (item_id,))

    return [r["name"] for r in cur.fetchall()]


def cleanup_unused_tags(conn):
    cur = conn.cursor()
    cur.execute("""
    DELETE FROM tags
    WHERE id NOT IN (
        SELECT DISTINCT tag_id FROM item_tags
    )
    """)
