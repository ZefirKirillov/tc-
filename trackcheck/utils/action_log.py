"""Единый лог тяжёлых действий для Render livetail.

Render показывает только stdout, поэтому пишем одной строкой
print(..., flush=True). Вызов — это только форматирование уже имеющихся
аргументов, без доп. запросов в БД/сеть (~микросекунды против
миллисекунд/секунд самих операций), на скорость не влияет.

Отключение: ACTION_LOG_ENABLED=0.
"""
import os
import time

_ENABLED = os.environ.get("ACTION_LOG_ENABLED", "1") not in ("0", "false", "no")
_STARTED_AT = time.monotonic()


def log_action(kind: str, user_id=None, detail: str = "") -> None:
    """Одна строка: [ACT] <uptime> kind=... user=... <detail>."""
    if not _ENABLED:
        return
    try:
        if detail and len(detail) > 160:
            detail = detail[:157] + "..."
        uptime = time.monotonic() - _STARTED_AT
        line = f"[ACT] +{uptime:8.1f}s kind={kind}"
        if user_id is not None:
            line += f" user={user_id}"
        if detail:
            line += f" | {detail}"
        print(line, flush=True)
    except Exception:
        pass
