import json
import os
import shutil
import subprocess

from analyzer import parse_title
from db import get_conn, set_tags


ARCHIVE_EXTS = {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".tar.gz", ".tar.bz2", ".tbz", ".tbz2", ".tar.xz", ".txz"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}


def _is_archive(filename: str) -> bool:
    lower = filename.lower()
    if lower.endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
        return True
    return os.path.splitext(lower)[1] in ARCHIVE_EXTS


def _is_image(filename: str) -> bool:
    return os.path.splitext(filename.lower())[1] in IMAGE_EXTS


def _format_size(num_bytes: int) -> str:
    value = float(num_bytes)
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_idx = 0
    while value >= 1024 and unit_idx < len(units) - 1:
        value /= 1024
        unit_idx += 1
    if unit_idx == 0:
        return f"{int(value)} {units[unit_idx]}"
    return f"{value:.1f} {units[unit_idx]}"


SEVEN_ZIP_PATH = r"D:\7-Zip\7z.exe"


def _find_7z_exe():
    if SEVEN_ZIP_PATH and os.path.isfile(SEVEN_ZIP_PATH):
        return SEVEN_ZIP_PATH
    return shutil.which("7z")


def _is_password_error_7z(output_text: str) -> bool:
    text = (output_text or "").lower()
    signals = (
        "wrong password",
        "enter password",
        "can not open encrypted archive",
        "data error in encrypted file",
        "headers error",
        # "encrypted",
    )
    return any(s in text for s in signals)


def _list_archive_paths_7z(path: str):
    seven_zip = _find_7z_exe()
    if not seven_zip:
        return []

    try:
        proc = subprocess.run(
            [seven_zip, "l", "-slt", "-ba", "-p__INVALID_PASSWORD__", path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=120,
        )
    except Exception:
        return []

    output = (proc.stdout or b"") + b"\n" + (proc.stderr or b"")
    output_text = output.decode("utf-8", errors="ignore").lower()
    if _is_password_error_7z(output_text):
        print(f"skip encrypted archive (password required): {os.path.basename(path)}")
        return []

    if proc.returncode != 0:
        return []

    paths = []
    for raw_line in proc.stdout.splitlines():
        line = raw_line.strip()
        if line.startswith(b"Path = "):
            name_bytes = line[7:]
            try:
                name = name_bytes.decode("mbcs")
            except Exception:
                name = name_bytes.decode("utf-8", errors="ignore")
            paths.append(name)
    return paths


def _read_file_from_archive_7z(path: str, filename: str):
    seven_zip = _find_7z_exe()
    if not seven_zip:
        return None

    try:
        proc = subprocess.run(
            [seven_zip, "e", "-so", "-p__INVALID_PASSWORD__", path, filename],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=120,
        )
    except Exception:
        return None

    output = (proc.stdout or b"") + b"\n" + (proc.stderr or b"")
    output_text = output.decode("utf-8", errors="ignore").lower()
    if _is_password_error_7z(output_text):
        print(f"skip encrypted archive (password required): {os.path.basename(path)}")
        return None

    if proc.returncode != 0:
        return None

    return proc.stdout


def extract_first_image_bytes(archive_path: str):
    if not _is_archive(archive_path):
        return None

    names = _list_archive_paths_7z(archive_path)
    if not names:
        return None

    images = [n for n in names if _is_image(n)]
    if not images:
        return None

    name = sorted(images, key=lambda x: x.lower())[0]
    return _read_file_from_archive_7z(archive_path, name)


def parse_archives_in_dir(input_dir: str, output_path: str = None, is_exists: int = None):
    """
    Recursively scan input_dir for archives, parse archive filenames, and
    write results to local_dir_res.json next to this script by default.
    """
    if not input_dir:
        raise ValueError("input_dir is required")
    if is_exists is None:
        raise ValueError("is_exists is required")

    input_dir = os.path.abspath(input_dir)

    results = []

    for root, _, files in os.walk(input_dir):
        for name in files:
            if not _is_archive(name):
                continue

            full_path = os.path.abspath(os.path.join(root, name))
            rel_name = os.path.splitext(name)[0]

            parsed = parse_title(rel_name)

            results.append({
                "path": full_path,
                "is_exists": is_exists,
                "parsed": parsed
            })

    if output_path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_path = os.path.join(script_dir, "local_dir_res.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return results


def import_local_dir_res_to_db(json_path: str = None):
    """
    Read local_dir_res.json and insert items into database.
    The image is the first image found inside each archive (if any).
    """
    if json_path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        json_path = os.path.join(script_dir, "local_dir_res.json")

    with open(json_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    conn = get_conn()
    cur = conn.cursor()

    titles = []
    for item in items:
        path = item.get("path")
        if not path:
            continue
        filename = os.path.basename(path)
        raw_title = os.path.splitext(filename)[0]
        titles.append(raw_title)

    dup_in_db = set()
    if titles:
        placeholders = ",".join(["?"] * len(titles))
        cur.execute(f"SELECT title FROM items WHERE title IN ({placeholders})", titles)
        dup_in_db = {r["title"] for r in cur.fetchall()}

    seen = set()
    total = len(items)
    for i, item in enumerate(items):
        if i % 10 == 0:  # 每10个打印一次进度
            print(f"处理进度: {i}/{total} ({i/total*100:.1f}%)")
            if i > 0:
                conn.commit()  # 定期提交事务，避免长时间占用数据库锁

        path = item.get("path")
        if not path:
            continue

        filename = os.path.basename(path)
        # 打印文件名和压缩包大小
        try:
            file_size = os.path.getsize(path)
            print(f"处理文件: {filename} ({_format_size(file_size)})")
        except OSError:
            print(f"处理文件: {filename} (无法获取文件大小)")
        
        raw_title = os.path.splitext(filename)[0]
        parsed = item.get("parsed") or parse_title(raw_title)

        img_bytes = extract_first_image_bytes(path)
        
        # 检查图片大小限制 (20MB)
        MAX_SIZE = 20 * 1024 * 1024  # 20MB
        if img_bytes and len(img_bytes) > MAX_SIZE:
            print(f"跳过大文件: {filename} ({_format_size(len(img_bytes))} > {_format_size(MAX_SIZE)})")
            img_bytes = None
        
        # 生成压缩图
        img_compressed = None
        if img_bytes:
            try:
                from main import compress_image_bytes
                img_compressed = compress_image_bytes(img_bytes)
                # 检查压缩后图片大小
                if img_compressed and len(img_compressed) > MAX_SIZE:
                    print(
                        f"跳过压缩后大文件: {filename} "
                        f"(compressed: {_format_size(len(img_compressed))} > {_format_size(MAX_SIZE)})"
                    )
                    img_bytes = None
                    img_compressed = None
            except Exception:
                img_compressed = None

        is_exists_flag = item.get("is_exists")

        if raw_title in seen:
            if is_exists_flag > 0:
                conn.close()
                raise ValueError(f"duplicate title in batch: {raw_title}")
            continue

        seen.add(raw_title)

        if raw_title in dup_in_db:
            if is_exists_flag > 0:
                conn.close()
                raise ValueError(f"duplicate title in db: {raw_title}")
            continue

        cur.execute("""
        INSERT INTO items(title,publish,author,author_tag,simple_title,remarks,img,img_compressed,is_exists)
        VALUES(?,?,?,?,?,?,?,?,?)
        """, (
            raw_title,
            parsed.get("publish"),
            parsed.get("author"),
            parsed.get("author_tag"),
            parsed.get("title"),
            ",".join(parsed.get("remarks") or []),
            img_bytes,
            img_compressed,
            is_exists_flag
        ))

        item_id = cur.lastrowid
        set_tags(conn, item_id, [])

    print(f"处理完成: {total} 个项目已插入数据库")
    conn.commit()
    conn.close()


def test():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
            DELETE FROM items WHERE id in (12, 11, 10, 9, 8)
            """)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    BASE_DIR = r"C:\Users\voidblank\Saved Games\0325"
    # parse_archives_in_dir(BASE_DIR, is_exists=2)
    import_local_dir_res_to_db() 
    # test()
