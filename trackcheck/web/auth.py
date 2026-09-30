"""Telegram Mini App auth: validates WebApp initData.

Protocol (per Telegram docs): initData is a query-string of key=value pairs
plus a `hash`. To validate:
  1. split pairs, drop `hash`
  2. sort keys alphabetically, join as "key=value" lines
  3. secret_key = HMAC_SHA256(key="WebAppData", msg=BOT_TOKEN)
  4. check HMAC_SHA256(key=secret_key, msg=data_check_string) == hash
Also enforces auth_date freshness (default max age 24h).
"""
import hashlib
import hmac
import json
import time
from typing import Optional
from urllib.parse import parse_qsl

from trackcheck.config import BOT_TOKEN

MAX_AUTH_AGE_SEC = 24 * 3600


def _check_hash(data_check_string: str, received_hash: str) -> bool:
    if not BOT_TOKEN:
        return False
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(calc, received_hash)


def validate_init_data(init_data: str, max_age_sec: int = MAX_AUTH_AGE_SEC) -> Optional[dict]:
    """Returns the parsed `user` dict on success, None on failure."""
    if not init_data or not BOT_TOKEN:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    if not _check_hash(data_check_string, received_hash):
        return None
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        return None
    if time.time() - auth_date > max_age_sec:
        return None
    try:
        user = json.loads(pairs.get("user", "{}"))
    except Exception:
        return None
    if not user.get("id"):
        return None
    return user
