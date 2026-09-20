from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict

from trackcheck.database.connection import db
from trackcheck.config import DEFAULT_TIMEZONE


_tz_cache: Dict[int, str] = {}



def get_user_timezone(user_id: int) -> str:
    cached = _tz_cache.get(user_id)
    if cached is not None:
        return cached
    cursor = db.execute('SELECT timezone FROM user_settings WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    tz = row[0] if (row and row[0]) else DEFAULT_TIMEZONE
    _tz_cache[user_id] = tz
    return tz



def set_user_timezone(user_id: int, tz_name: str):
    db.execute('''
        INSERT INTO user_settings (user_id, timezone) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET timezone = excluded.timezone
    ''', (user_id, tz_name))
    db.commit()
    _tz_cache[user_id] = tz_name



def _resolve_tz(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo(DEFAULT_TIMEZONE)



def user_now(user_id: int) -> datetime:
    """Текущее время в часовом поясе пользователя (а не сервера)."""
    return datetime.now(_resolve_tz(get_user_timezone(user_id)))



def user_today_str(user_id: int, fmt: str = '%Y-%m-%d') -> str:
    return user_now(user_id).strftime(fmt)



def user_today_date(user_id: int):
    return user_now(user_id).date()



def user_weekday(user_id: int) -> int:
    return user_now(user_id).weekday()
