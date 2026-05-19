import argparse
import os
import sqlite3
import subprocess
from db import get_conn
from local_dir import _find_7z_exe, _is_archive, _list_archive_paths_7z, _read_file_from_archive_7z, _is_image


def build_archive_index(paths):
    archive_map = {}
    for root_path in paths:
        if not os.path.isdir(root_path):
            print(f"skip missing path: {root_path}")
            continue
        for root, _, files in os.walk(root_path):
            for name in files:
                if not _is_archive(name):
                    continue
                base = os.path.splitext(name)[0].strip().lower()
                full_path = os.path.join(root, name)
                archive_map.setdefault(base, []).append(full_path)
    return archive_map


def find_first_image_in_archive(archive_path):
    names = _list_archive_paths_7z(archive_path)
    if not names:
        return None, None
    images = [n for n in names if _is_image(n)]
    if not images:
        return None, None
    first_image = sorted(images, key=lambda x: x.lower())[0]
    content = _read_file_from_archive_7z(archive_path, first_image)
    if not content:
        return None, None
    return first_image, content


def ensure_cover_img_table(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS cover_img (
        item_id INTEGER PRIMARY KEY,
        img BLOB,
        FOREIGN KEY(item_id) REFERENCES items(id)
    )
    """)
    conn.commit()


def get_items_needing_fix(conn):
    cur = conn.cursor()
    cur.execute("""
    SELECT i.id, i.title
    FROM items i
    LEFT JOIN cover_img c ON c.item_id = i.id
    WHERE i.img_compressed IS NOT NULL
      AND (c.item_id IS NULL OR c.img IS NULL)
    ORDER BY i.id
    """)
    return cur.fetchall()


def insert_cover_img(conn, item_id, img_bytes):
    cur = conn.cursor()
    cur.execute("SELECT item_id FROM cover_img WHERE item_id=?", (item_id,))
    if cur.fetchone():
        cur.execute("UPDATE cover_img SET img=? WHERE item_id=?", (img_bytes, item_id))
    else:
        cur.execute("INSERT INTO cover_img(item_id, img) VALUES(?,?)", (item_id, img_bytes))


def main():
    paths = [
        r'C:\Users\voidblank\Saved Games\done-wait',
        r'C:\Users\voidblank\Saved Games\done',
        r'C:\Users\voidblank\Saved Games\0618',
        r'C:\Users\voidblank\Saved Games\0402',
        r'C:\Users\voidblank\Saved Games\0316',
        r'C:\Users\voidblank\Saved Games\0325',
    ]
    parser = argparse.ArgumentParser(description="Fix missing cover_img rows by extracting first image from corresponding archives.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to the database")
    parser.add_argument("--verbose", action="store_true", help="Show more details")
    parser.add_argument("--batch", type=int, default=10, help="Commit every N items")
    args = parser.parse_args()

    z7 = _find_7z_exe()
    if not z7:
        raise RuntimeError("7z executable not found. Please install 7-Zip or configure the path in local_dir.py.")

    archive_map = build_archive_index(paths)
    print(f"indexed {sum(len(v) for v in archive_map.values())} archives from {len(paths)} paths")

    conn = get_conn()
    ensure_cover_img_table(conn)
    items = get_items_needing_fix(conn)
    total = len(items)
    print(f"found {total} items needing cover_img fix")
    if total == 0:
        conn.close()
        return

    fixed = 0
    skipped = 0
    unresolved = []

    for idx, row in enumerate(items, start=1):
        item_id = row["id"]
        title = (row["title"] or "").strip()
        lookup = title.lower()
        candidates = archive_map.get(lookup, [])
        if not candidates:
            print(f"[{idx}/{total}] no archive found for item {item_id} title={title}")
            unresolved.append((item_id, title))
            skipped += 1
            continue

        success = False
        for archive_path in candidates:
            if args.verbose:
                print(f"  try archive {archive_path}")
            image_name, raw = find_first_image_in_archive(archive_path)
            if not raw:
                if args.verbose:
                    print(f"    no image extracted from {archive_path}")
                continue
            print(f"[{idx}/{total}] fix item {item_id} title={title} from {os.path.basename(archive_path)}/{image_name}")
            if not args.dry_run:
                insert_cover_img(conn, item_id, raw)
            fixed += 1
            success = True
            break

        if not success:
            print(f"[{idx}/{total}] no valid image found for item {item_id} title={title}")
            unresolved.append((item_id, title))
            skipped += 1

        if not args.dry_run and idx % args.batch == 0:
            conn.commit()

    if not args.dry_run:
        conn.commit()
    conn.close()

    print(f"done: fixed={fixed}, skipped={skipped}, total={total}")
    if unresolved and args.verbose:
        print("unresolved items:")
        for item_id, title in unresolved:
            print(f"  {item_id}: {title}")


if __name__ == "__main__":
    main()
