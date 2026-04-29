import base64
from contextlib import asynccontextmanager
import hashlib
import io
import mimetypes
import os
import shutil
import sqlite3
import subprocess
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, UploadFile, File, Form, Response, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from analyzer import parse_title
from db import *
from local_dir import IMAGE_EXTS, _find_7z_exe
import time

PREVIEW_SOURCE_DIRS = {
    1: [
        # r"D:\archives\exists",
        r"D:\BaiduNetdiskDownload\test01",
    ],
    2: [
        # r"D:\archives\pending",
        r"D:\BaiduNetdiskDownload\test01",
    ],
}
PREVIEW_ARCHIVE_EXTS = (".zip", ".rar", ".7z")
PREVIEW_TEMP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".preview_cache")
PREVIEW_PRELOAD_AHEAD = 3
PREVIEW_7Z_TIMEOUT = 600
PREVIEW_MAX_CACHE_DIRS = 12
_preview_extract_locks = {}
_preview_extract_locks_guard = threading.Lock()


def _preview_sort_key(path_text: str):
    parts = []
    token = ""
    token_is_digit = None
    for ch in path_text.lower():
        is_digit = ch.isdigit()
        if token and token_is_digit == is_digit:
            token += ch
        else:
            if token:
                parts.append(int(token) if token_is_digit else token)
            token = ch
            token_is_digit = is_digit
    if token:
        parts.append(int(token) if token_is_digit else token)
    return parts


def _get_preview_lock(cache_key: str):
    with _preview_extract_locks_guard:
        lock = _preview_extract_locks.get(cache_key)
        if lock is None:
            lock = threading.Lock()
            _preview_extract_locks[cache_key] = lock
        return lock


def _remove_preview_dir(path: str):
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def _cleanup_preview_cache_on_startup():
    if not os.path.isdir(PREVIEW_TEMP_ROOT):
        return
    for name in os.listdir(PREVIEW_TEMP_ROOT):
        full_path = os.path.join(PREVIEW_TEMP_ROOT, name)
        if os.path.isdir(full_path):
            _remove_preview_dir(full_path)


def _cleanup_preview_cache_overflow():
    if PREVIEW_MAX_CACHE_DIRS < 1:
        return
    os.makedirs(PREVIEW_TEMP_ROOT, exist_ok=True)
    cache_dirs = []
    for name in os.listdir(PREVIEW_TEMP_ROOT):
        full_path = os.path.join(PREVIEW_TEMP_ROOT, name)
        if os.path.isdir(full_path):
            try:
                mtime = os.path.getmtime(full_path)
            except OSError:
                mtime = 0
            cache_dirs.append((mtime, full_path))
    if len(cache_dirs) <= PREVIEW_MAX_CACHE_DIRS:
        return
    cache_dirs.sort(key=lambda item: item[0])
    for _, full_path in cache_dirs[:-PREVIEW_MAX_CACHE_DIRS]:
        _remove_preview_dir(full_path)


def _get_preview_item_row(item_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT id, title, is_exists, is_deleted
    FROM items
    WHERE id=?
    """, (item_id,))
    row = cur.fetchone()
    conn.close()
    if not row or row["is_deleted"]:
        raise HTTPException(status_code=404, detail="item not found")
    return row


def _get_preview_source_dirs(is_exists: int):
    roots = PREVIEW_SOURCE_DIRS.get(is_exists) or []
    return [os.path.abspath(p) for p in roots if p]


def _find_archive_for_item(title: str, is_exists: int):
    roots = _get_preview_source_dirs(is_exists)
    if not roots:
        raise HTTPException(status_code=500, detail=f"preview paths not configured for state {is_exists}")

    for root in roots:
        for ext in PREVIEW_ARCHIVE_EXTS:
            candidate = os.path.join(root, f"{title}{ext}")
            if os.path.isfile(candidate):
                return os.path.abspath(candidate)

    raise HTTPException(status_code=404, detail=f"archive not found for title: {title}")


def _list_extracted_images(extract_dir: str):
    images = []
    for root, _, files in os.walk(extract_dir):
        for name in files:
            ext = os.path.splitext(name.lower())[1]
            if ext not in IMAGE_EXTS:
                continue
            full_path = os.path.join(root, name)
            rel_path = os.path.relpath(full_path, extract_dir)
            images.append(rel_path)
    images.sort(key=_preview_sort_key)
    return images


def _ensure_archive_extracted(archive_path: str):
    seven_zip = _find_7z_exe()
    if not seven_zip:
        raise HTTPException(status_code=500, detail="7z executable not found")

    archive_stat = os.stat(archive_path)
    cache_key_src = f"{archive_path}|{archive_stat.st_mtime_ns}|{archive_stat.st_size}"
    cache_key = hashlib.sha1(cache_key_src.encode("utf-8")).hexdigest()[:16]
    extract_dir = os.path.join(PREVIEW_TEMP_ROOT, cache_key)
    ready_flag = os.path.join(extract_dir, ".ready")
    lock = _get_preview_lock(cache_key)

    with lock:
        if not os.path.isfile(ready_flag):
            os.makedirs(extract_dir, exist_ok=True)
            proc = subprocess.run(
                [seven_zip, "x", archive_path, f"-o{extract_dir}", "-y", "-p__INVALID_PASSWORD__"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=PREVIEW_7Z_TIMEOUT,
            )
            if proc.returncode != 0:
                output = ((proc.stdout or b"") + b"\n" + (proc.stderr or b"")).decode("utf-8", errors="ignore")
                _remove_preview_dir(extract_dir)
                raise HTTPException(status_code=500, detail=f"archive extract failed: {output[:300]}")

            images = _list_extracted_images(extract_dir)
            if not images:
                _remove_preview_dir(extract_dir)
                raise HTTPException(status_code=404, detail="no previewable images found in archive")

            Path(ready_flag).write_text("\n".join(images), encoding="utf-8")
            _cleanup_preview_cache_overflow()

    try:
        images = Path(ready_flag).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        images = _list_extracted_images(extract_dir)

    if not images:
        raise HTTPException(status_code=404, detail="no previewable images found in archive")

    return extract_dir, images


def _get_preview_pages(item_id: int):
    row = _get_preview_item_row(item_id)
    is_exists = row["is_exists"]
    if is_exists not in (1, 2):
        raise HTTPException(status_code=400, detail="preview only available for existing or pending items")

    archive_path = _find_archive_for_item(row["title"], is_exists)
    extract_dir, pages = _ensure_archive_extracted(archive_path)
    return {
        "title": row["title"],
        "state": is_exists,
        "archive_path": archive_path,
        "extract_dir": extract_dir,
        "pages": pages,
    }


def on_startup():
    _cleanup_preview_cache_on_startup()


@asynccontextmanager
async def lifespan(app: FastAPI):
    on_startup()
    yield


app = FastAPI(lifespan=lifespan)

init_db()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/add")
async def add_item(
        title: str = Form(...),
        tags: str = Form(""),
        img: Optional[UploadFile] = File(None)
):
    conn = get_conn()
    cur = conn.cursor()

    parsed = parse_title(title)

    img_bytes = None
    img_compressed = None

    if img:
        img_bytes = await img.read()
        img_compressed = compress_image_bytes(img_bytes)

    try:
        cur.execute("""
        INSERT INTO items(title,publish,author,author_tag,simple_title,remarks,img_compressed)
        VALUES(?,?,?,?,?,?,?)
        """, (
            title,
            parsed["publish"],
            parsed["author"],
            parsed.get("author_tag"),
            parsed["title"],
            ",".join(parsed["remarks"]),
            img_compressed
        ))
    except sqlite3.IntegrityError:
        conn.close()
        return {"ok": False, "error": "TITLE_EXISTS"}
    item_id = cur.lastrowid
    if img:     
        cur.execute("DELETE FROM cover_img WHERE item_id=?", (item_id,))
        cur.execute("INSERT INTO cover_img(item_id, img) VALUES(?,?)", (item_id, img_bytes))

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    set_tags(conn, item_id, tag_list)

    conn.commit()
    conn.close()   
    return {"ok": True}


@app.post("/api/parse_title")
async def parse_title_api(title: str = Form(...)):
    return parse_title(title)


@app.post("/api/update")
async def update_item(
        item_id: int = Form(...),
        publish: str = Form(""),
        author: str = Form(""),
        author_tag: str = Form(""),
        simple_title: str = Form(""),
        remarks: str = Form(""),
        tags: str = Form(""),
        is_exists: int = Form(1),
        img: Optional[UploadFile] = File(None)
):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    UPDATE items
    SET publish=?, author=?, author_tag=?, simple_title=?, remarks=?, is_exists=?
    WHERE id=?
    """, (publish, author, author_tag, simple_title, remarks, is_exists, item_id))

    if img:
        img_bytes = await img.read()
        img_compressed = compress_image_bytes(img_bytes)
        cur.execute("UPDATE items SET img_compressed=? WHERE id=?", (img_compressed, item_id))
        cur.execute("DELETE FROM cover_img WHERE item_id=?", (item_id,))
        cur.execute("INSERT INTO cover_img(item_id, img) VALUES(?,?)", (item_id, img_bytes))

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    set_tags(conn, item_id, tag_list)
    cleanup_unused_tags(conn)

    conn.commit()

    # 返回更新后的完整条目
    cur.execute("SELECT * FROM items WHERE id=?", (item_id,))
    row = cur.fetchone()
    result = dict(row)
    if row["img_compressed"]:
        img_bytes = row["img_compressed"]
        img64 = base64.b64encode(img_bytes).decode()
        img_mime = guess_mime(img_bytes)
    else:
        img64 = None
        img_mime = None
    result["img"] = img64
    result["img_mime"] = img_mime
    result["img_compressed"] = None  # 不直接返回压缩图数据
    result["tags"] = get_tags(conn, item_id)
    result["custom_marks"] = ",".join(result["tags"])
    conn.close()
    return {"ok": True, "item": result}


@app.post("/api/delete")
async def delete_item(item_id: int = Form(...)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE items SET is_deleted=1 WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


def compress_image_bytes(raw_bytes: bytes, max_size: int = 320, quality: int = 65) -> bytes:
    try:
        from PIL import Image
    except ImportError:
        return raw_bytes

    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            has_alpha = img.mode in ("RGBA", "LA") or ("transparency" in img.info)
            img.thumbnail((max_size, max_size))
            buf = io.BytesIO()
            if has_alpha:
                img = img.convert("RGBA")
                # PNG压缩等级提升到9（最大）
                img.save(buf, format="PNG", optimize=True, compress_level=9)
            else:
                img = img.convert("RGB")
                # JPEG质量降低，subsampling=2（4:2:0）进一步压缩
                img.save(
                    buf,
                    format="JPEG",
                    quality=quality,
                    optimize=True,
                    progressive=True,
                    subsampling=2
                )
            return buf.getvalue()
    except Exception:
        return raw_bytes


def guess_mime(raw_bytes: bytes) -> str:
    if not raw_bytes:
        return "application/octet-stream"

    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"

    if raw_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"

    if raw_bytes[:2] == b"BM":
        return "image/bmp"

    if len(raw_bytes) > 12 and raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WEBP":
        return "image/webp"

    return "application/octet-stream"


@app.get("/api/item_img")
def item_img(item_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT img FROM cover_img WHERE item_id=?", (item_id,))
    row = cur.fetchone()
    conn.close()

    if not row or not row["img"]:
        raise HTTPException(status_code=404)

    raw_bytes = row["img"]
    return Response(content=raw_bytes, media_type=guess_mime(raw_bytes))


@app.get("/api/preview/info")
def preview_info(item_id: int):
    preview = _get_preview_pages(item_id)
    return {
        "ok": True,
        "item_id": item_id,
        "title": preview["title"],
        "archive_path": preview["archive_path"],
        "total_pages": len(preview["pages"]),
        "preload_ahead": PREVIEW_PRELOAD_AHEAD,
    }


@app.get("/api/preview/page")
def preview_page(item_id: int, page: int):
    preview = _get_preview_pages(item_id)
    pages = preview["pages"]
    if page < 1 or page > len(pages):
        raise HTTPException(status_code=404, detail="page not found")

    rel_path = pages[page - 1]
    full_path = os.path.abspath(os.path.join(preview["extract_dir"], rel_path))
    extract_dir = os.path.abspath(preview["extract_dir"])
    if not full_path.startswith(extract_dir + os.sep) and full_path != extract_dir:
        raise HTTPException(status_code=400, detail="invalid preview page path")

    media_type = mimetypes.guess_type(full_path)[0] or "application/octet-stream"
    return FileResponse(full_path, media_type=media_type, filename=os.path.basename(full_path))


@app.get("/api/items")
def items(
        page: int = 1,
        q: str = "",
        publish: str = "",
        author_tag: str = "",
        author_tag_mode: str = "like",
        tags: str = "",
        show_img: bool = True,
        exists_filter: str = "all",
        page_size: int = 20,
        sort_by: str = "id"
):
    conn = get_conn()
    cur = conn.cursor()

    if page_size < 1:
        page_size = 20
    offset = (page - 1) * page_size

    fields = [
        "i.id", "i.title", "i.publish", "i.author", "i.author_tag",
        "i.simple_title", "i.remarks", "i.is_exists"
    ]

    if show_img:
        fields.append("i.img_compressed")

    fields.append("GROUP_CONCAT(DISTINCT t.name) AS tags")

    sql = f"SELECT {', '.join(fields)} FROM items i"
    count_sql = "SELECT COUNT(DISTINCT i.id) FROM items i"

    where = []
    params = []
    joins = []
    tag_list = None

    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        if tag_list:
            joins.extend([
                "JOIN item_tags itf ON i.id = itf.item_id",
                "JOIN tags tf ON itf.tag_id = tf.id"
            ])
            placeholders = ",".join(["?"] * len(tag_list))
            where.append(f"tf.name IN ({placeholders})")
            params.extend(tag_list)

    # For full tags list per item, use LEFT JOIN on item_tags/tags.
    joins.extend([
        "LEFT JOIN item_tags it ON i.id = it.item_id",
        "LEFT JOIN tags t ON it.tag_id = t.id"
    ])

    if q:
        where.append("i.title LIKE ?")
        params.append(f"%{q}%")

    if publish:
        where.append("i.publish = ?")
        params.append(publish)

    if author_tag:
        if author_tag_mode == "equal":
            where.append("i.author_tag = ?")
            params.append(author_tag)
        else:
            where.append("i.author_tag LIKE ?")
            params.append(f"%{author_tag}%")

    if exists_filter == "exists":
        where.append("i.is_exists = 1")
    elif exists_filter == "pending":
        where.append("i.is_exists = 2")

    # is_deleted 默认存在，并且永远过滤被软删除项
    where.append("i.is_deleted = 0")

    if joins:
        sql += " " + " ".join(joins)
        # count_sql只需要与tags筛选相关的内连接
        if tag_list:
            count_sql += " " + " ".join(joins[:2])

    if where:
        where_sql = " WHERE " + " AND ".join(where)
        sql += where_sql
        count_sql += where_sql

    valid_sort_fields = ["id", "title", "publish", "author", "author_tag", "simple_title", "remarks"]
    if sort_by not in valid_sort_fields:
        sort_by = "id"

    sql += f" GROUP BY i.id ORDER BY i.{sort_by} DESC LIMIT ? OFFSET ?"

    count_params = list(params)
    query_params = list(params)
    query_params.extend([page_size, offset])

    cur.execute(count_sql, count_params)
    total = cur.fetchone()[0]

    start_time = time.time()
    cur.execute(sql, query_params)
    rows = cur.fetchall()
    end_time = time.time()
    print(f"Query executed in {end_time - start_time:.2f} seconds, total items: {total}")

    result = []

    for r in rows:
        tags_text = r["tags"] or ""
        tags_list = [t for t in tags_text.split(",") if t]

        img64 = None
        img_mime = None

        if show_img and r["img_compressed"]:
            img64 = base64.b64encode(r["img_compressed"]).decode()
            img_mime = guess_mime(r["img_compressed"])

        result.append({
            "id": r["id"],
            "title": r["title"],
            "publish": r["publish"],
            "author": r["author"],
            "author_tag": r["author_tag"],
            "simple_title": r["simple_title"],
            "remarks": r["remarks"],
            "tags": tags_list,
            "custom_marks": ",".join(tags_list),
            "img": img64,
            "img_mime": img_mime,
            "is_exists": r["is_exists"]
        })

    conn.close()
    return {"items": result, "total": total}


@app.get("/api/tags")
def get_all_tags(include_all: bool = False):
    conn = get_conn()
    cur = conn.cursor()

    sql = """
        SELECT DISTINCT t.name
        FROM tags t
        JOIN item_tags it ON t.id = it.tag_id
        JOIN items i ON it.item_id = i.id AND i.is_deleted = 0
        WHERE it.item_id IS NOT NULL
    """

    if not include_all:
        sql += " AND i.is_exists = 1"

    sql += " ORDER BY t.name"

    cur.execute(sql)

    rows = cur.fetchall()

    conn.close()

    return [r["name"] for r in rows]


@app.get("/api/publishes")
def get_all_publishes():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT DISTINCT publish
    FROM items
    WHERE publish IS NOT NULL AND publish != ''
    ORDER BY publish
    """)

    rows = cur.fetchall()

    conn.close()

    return [r["publish"] for r in rows]


@app.get("/api/author_tags")
def get_all_author_tags():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT DISTINCT author_tag
    FROM items
    WHERE author_tag IS NOT NULL AND author_tag != ''
    ORDER BY author_tag
    """)

    rows = cur.fetchall()

    conn.close()

    return [r["author_tag"] for r in rows]


if __name__ == "__main__":
    import uvicorn
    # pip install fastapi uvicorn jinja2 python-multipart
    uvicorn.run(app, host="0.0.0.0", port=8000)
