import sqlite3
from main import compress_image_bytes
from db import get_conn

def generate_all_compressed_images():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, img FROM items WHERE img IS NOT NULL")
    rows = cur.fetchall()
    for row in rows:
        item_id = row["id"]
        img_bytes = row["img"]
        if not img_bytes:
            continue
        img_compressed = compress_image_bytes(img_bytes)
        cur.execute("UPDATE items SET img_compressed=? WHERE id=?", (img_compressed, item_id))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    generate_all_compressed_images()