from typing import Dict, List

user_last_menu: Dict[int, int] = {}
user_temp_messages: Dict[int, Dict[str, int]] = {}
user_history_page: Dict[int, int] = {}
user_food_history_page: Dict[int, int] = {}
user_welcome_message: Dict[int, int] = {}
user_nav: Dict[int, List[str]] = {}
scheduler = None
bot_instance = None
# Последний ID уведомления (single-slot). In-memory кэш, чтобы middleware
# чистки не ходил в БД (сеть Turso) при каждом взаимодействии; БД — бэкап
# на случай рестарта.
user_notify_msg: Dict[int, int] = {}


def nav_push(user_id: int, screen: str):
    """Отметить, что сейчас показан этот экран (для последующего «Назад»)."""
    stack = user_nav.setdefault(user_id, [])
    if not stack or stack[-1] != screen:
        stack.append(screen)


def nav_current(user_id: int) -> str:
    stack = user_nav.get(user_id) or []
    return stack[-1] if stack else "main"


def nav_pop(user_id: int) -> str:
    stack = user_nav.get(user_id)
    if stack:
        stack.pop()
    return nav_current(user_id)
