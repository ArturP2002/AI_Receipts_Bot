"""Снимок SQLite для админской команды (консистентно при работающем боте)."""

import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from database import db


def sqlite_db_path() -> Path:
    raw = db.database
    p = Path(raw)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


def create_sqlite_backup_file() -> tuple[str, str]:
    """
    Создаёт временный файл с копией БД.
    Возвращает (абсолютный путь к файлу, имя для отправки пользователю).
    Вызывающий обязан удалить файл после использования.
    """
    src_path = sqlite_db_path()
    if not src_path.is_file():
        raise FileNotFoundError(f"Файл базы не найден: {src_path}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    download_name = f"AI_Receipts_Bot_backup_{stamp}.db"

    fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        src = sqlite3.connect(str(src_path), timeout=60.0)
        try:
            dst = sqlite3.connect(tmp_path, timeout=60.0)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return tmp_path, download_name
