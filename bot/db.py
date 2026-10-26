"""База данных SQLite. В базе только file_id и текст, сами файлы лежат у Telegram."""
import os
import time
from contextlib import asynccontextmanager
from typing import Optional

import aiosqlite

_db_path = "data/bot.db"
_dirty = False
_last_write = 0.0


def mark_dirty() -> None:
    """Запоминаем, что база изменилась и бэкап устарел."""
    global _dirty, _last_write
    _dirty = True
    _last_write = time.monotonic()


def is_dirty(quiet_seconds: float = 0) -> bool:
    return _dirty and (time.monotonic() - _last_write) >= quiet_seconds


def clear_dirty() -> None:
    global _dirty
    _dirty = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,              -- photo | pdf | document | text
    date TEXT NOT NULL,              -- ГГГГ-ММ-ДД
    file_id TEXT,
    file_unique_id TEXT,
    file_name TEXT,
    text TEXT,
    caption TEXT,
    important INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_materials_subject_date ON materials(subject_id, date);
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS material_tags (
    material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (material_id, tag_id)
);
CREATE TABLE IF NOT EXISTS teachers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    contacts TEXT NOT NULL DEFAULT '',
    consultations TEXT NOT NULL DEFAULT '',
    how_accepts TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

TEACHER_FIELDS = ("name", "contacts", "consultations", "how_accepts", "notes")


@asynccontextmanager
async def connect():
    async with aiosqlite.connect(_db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        db.row_factory = aiosqlite.Row
        yield db


async def init(path: str) -> None:
    global _db_path
    _db_path = path
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    async with connect() as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def _all(sql: str, params=()) -> list[dict]:
    async with connect() as db:
        cur = await db.execute(sql, params)
        return [dict(r) for r in await cur.fetchall()]


async def _one(sql: str, params=()) -> Optional[dict]:
    rows = await _all(sql, params)
    return rows[0] if rows else None


async def _exec(sql: str, params=()) -> int:
    async with connect() as db:
        cur = await db.execute(sql, params)
        await db.commit()
        mark_dirty()
        return cur.lastrowid


# ---------- Предметы ----------
async def list_subjects() -> list[dict]:
    rows = await _all(
        """SELECT s.id, s.name,
                  (SELECT COUNT(*) FROM materials m WHERE m.subject_id = s.id) AS cnt,
                  (SELECT COUNT(*) FROM materials m WHERE m.subject_id = s.id AND m.important = 1) AS imp
           FROM subjects s"""
    )
    rows.sort(key=lambda r: r["name"].casefold())
    return rows


async def get_subject(subject_id: int) -> Optional[dict]:
    return await _one(
        """SELECT s.id, s.name,
                  (SELECT COUNT(*) FROM materials m WHERE m.subject_id = s.id) AS cnt,
                  (SELECT COUNT(*) FROM materials m WHERE m.subject_id = s.id AND m.important = 1) AS imp
           FROM subjects s WHERE s.id = ?""",
        (subject_id,),
    )


async def add_subject(name: str) -> tuple[int, bool]:
    """Возвращает (id, создан_ли_новый). Если такой предмет есть, вернёт его id."""
    name = " ".join(name.split())
    for s in await list_subjects():
        if s["name"].casefold() == name.casefold():
            return s["id"], False
    return await _exec("INSERT INTO subjects (name) VALUES (?)", (name,)), True


async def rename_subject(subject_id: int, name: str) -> bool:
    name = " ".join(name.split())
    for s in await list_subjects():
        if s["id"] != subject_id and s["name"].casefold() == name.casefold():
            return False
    await _exec("UPDATE subjects SET name = ? WHERE id = ?", (name, subject_id))
    return True


async def delete_subject(subject_id: int) -> None:
    await _exec("DELETE FROM subjects WHERE id = ?", (subject_id,))


# ---------- Материалы ----------
async def add_material(
    subject_id: int,
    kind: str,
    date: str,
    file_id: str = None,
    file_unique_id: str = None,
    file_name: str = None,
    text: str = None,
    caption: str = None,
) -> int:
    return await _exec(
        """INSERT INTO materials
           (subject_id, kind, date, file_id, file_unique_id, file_name, text, caption)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (subject_id, kind, date, file_id, file_unique_id, file_name, text, caption),
    )


async def get_material(material_id: int) -> Optional[dict]:
    return await _one(
        """SELECT m.*, s.name AS subject_name,
                  (SELECT GROUP_CONCAT(t.name, ', ') FROM material_tags mt
                   JOIN tags t ON t.id = mt.tag_id WHERE mt.material_id = m.id) AS tags_str
           FROM materials m JOIN subjects s ON s.id = m.subject_id
           WHERE m.id = ?""",
        (material_id,),
    )


async def list_materials(subject_id: int, flt: str = "all") -> list[dict]:
    """flt: all | imp | t<id тега> | d<ГГГГММДД>_<ГГГГММДД>"""
    sql = """SELECT m.*,
                    (SELECT GROUP_CONCAT(t.name, ', ') FROM material_tags mt
                     JOIN tags t ON t.id = mt.tag_id WHERE mt.material_id = m.id) AS tags_str
             FROM materials m WHERE m.subject_id = ?"""
    params: list = [subject_id]
    if flt == "imp":
        sql += " AND m.important = 1"
    elif flt.startswith("t") and flt[1:].isdigit():
        sql += " AND EXISTS (SELECT 1 FROM material_tags x WHERE x.material_id = m.id AND x.tag_id = ?)"
        params.append(int(flt[1:]))
    elif flt.startswith("d") and "_" in flt:
        a, b = flt[1:].split("_")
        sql += " AND m.date BETWEEN ? AND ?"
        params += [f"{a[:4]}-{a[4:6]}-{a[6:]}", f"{b[:4]}-{b[4:6]}-{b[6:]}"]
    sql += " ORDER BY m.date DESC, m.id DESC"
    return await _all(sql, params)


async def toggle_important(material_id: int) -> None:
    await _exec(
        "UPDATE materials SET important = 1 - important WHERE id = ?", (material_id,)
    )


async def delete_material(material_id: int) -> None:
    await _exec("DELETE FROM materials WHERE id = ?", (material_id,))


# ---------- Теги ----------
async def material_tags(material_id: int) -> list[dict]:
    return await _all(
        """SELECT t.id, t.name FROM tags t
           JOIN material_tags mt ON mt.tag_id = t.id
           WHERE mt.material_id = ? ORDER BY t.name""",
        (material_id,),
    )


async def add_tags(material_id: int, names: list[str]) -> None:
    async with connect() as db:
        for raw in names:
            name = " ".join(raw.replace("#", " ").split()).casefold()[:30]
            if not name:
                continue
            await db.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
            cur = await db.execute("SELECT id FROM tags WHERE name = ?", (name,))
            tag_id = (await cur.fetchone())["id"]
            await db.execute(
                "INSERT OR IGNORE INTO material_tags (material_id, tag_id) VALUES (?, ?)",
                (material_id, tag_id),
            )
        await db.commit()
    mark_dirty()


async def remove_tag(material_id: int, tag_id: int) -> None:
    await _exec(
        "DELETE FROM material_tags WHERE material_id = ? AND tag_id = ?",
        (material_id, tag_id),
    )


async def tags_for_subject(subject_id: int) -> list[dict]:
    return await _all(
        """SELECT t.id, t.name, COUNT(*) AS cnt FROM tags t
           JOIN material_tags mt ON mt.tag_id = t.id
           JOIN materials m ON m.id = mt.material_id
           WHERE m.subject_id = ? GROUP BY t.id ORDER BY cnt DESC, t.name""",
        (subject_id,),
    )


# ---------- Поиск ----------
async def search_materials(query: str, limit: int = 30) -> list[dict]:
    """Поиск в Python, потому что SQLite не умеет регистронезависимо искать кириллицу."""
    words = [w for w in query.casefold().split() if w]
    if not words:
        return []
    rows = await _all(
        """SELECT m.*, s.name AS subject_name,
                  (SELECT GROUP_CONCAT(t.name, ' ') FROM material_tags mt
                   JOIN tags t ON t.id = mt.tag_id WHERE mt.material_id = m.id) AS tags_str
           FROM materials m JOIN subjects s ON s.id = m.subject_id
           ORDER BY m.date DESC, m.id DESC"""
    )
    found = []
    for r in rows:
        hay = " ".join(
            [
                r["subject_name"] or "",
                r["text"] or "",
                r["caption"] or "",
                r["file_name"] or "",
                r["tags_str"] or "",
                "важно" if r["important"] else "",
            ]
        ).casefold()
        if all(w in hay for w in words):
            found.append(r)
            if len(found) >= limit:
                break
    return found


# ---------- Преподаватели ----------
async def list_teachers() -> list[dict]:
    rows = await _all("SELECT * FROM teachers")
    rows.sort(key=lambda r: r["name"].casefold())
    return rows


async def get_teacher(teacher_id: int) -> Optional[dict]:
    return await _one("SELECT * FROM teachers WHERE id = ?", (teacher_id,))


async def add_teacher(**fields) -> int:
    values = [fields.get(f, "") or "" for f in TEACHER_FIELDS]
    return await _exec(
        "INSERT INTO teachers (name, contacts, consultations, how_accepts, notes) VALUES (?, ?, ?, ?, ?)",
        values,
    )


async def update_teacher(teacher_id: int, field: str, value: str) -> None:
    if field not in TEACHER_FIELDS:
        raise ValueError("Неизвестное поле")
    await _exec(f"UPDATE teachers SET {field} = ? WHERE id = ?", (value, teacher_id))


async def delete_teacher(teacher_id: int) -> None:
    await _exec("DELETE FROM teachers WHERE id = ?", (teacher_id,))


# ---------- Служебное ----------
async def is_empty() -> bool:
    row = await _one(
        """SELECT (SELECT COUNT(*) FROM subjects) + (SELECT COUNT(*) FROM materials)
                  + (SELECT COUNT(*) FROM teachers) AS n"""
    )
    return not row or row["n"] == 0
