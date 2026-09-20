import re
from datetime import datetime
from typing import Optional

from trackcheck.utils.dates import user_today_date
from trackcheck.config import WEEKDAY_NAMES


def get_time_greeting(name: str) -> str:
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return f"Бодрячком, {name}! 🌅"
    elif 12 <= hour < 17:
        return f"Как погодка, {name} ?☀️"
    elif 17 <= hour < 22:
        return f"Доообрый Вечер, {name}! 🌆"
    else:
        return f"Не спится, {name}? 🌙"



def create_new_progress_bar(current: int, max_val: int = 10) -> str:
    filled = min(current, max_val)
    empty = max_val - filled
    return "🔳" * filled + "◼️" * empty



def create_short_progress_bar(rating: int, total: int = 5) -> str:
    filled = round(rating / 10 * total)
    filled = min(filled, total)
    empty = total - filled
    return "🔳" * filled + "◼️" * empty



def create_workout_progress_bar(current: int, goal: int) -> str:
    if goal == 0:
        return "◼️" * 12 + " 0%"
    percentage = min(current / goal, 1.0)
    filled = int(12 * percentage)
    empty = 12 - filled
    return "🔳" * filled + "◼️" * empty + f" {int(percentage * 100)}%"



def strip_markdown(text: str) -> str:
    """Убирает markdown-разметку и лишние эмодзи из ответов ИИ."""
    import re, unicodedata
    # Убираем markdown
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\*(.+?)\*', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'__(.+?)__', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'_(.+?)_', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Ограничиваем количество эмодзи: оставляем максимум 1 эмодзи подряд
    def is_emoji(ch):
        cp = ord(ch)
        return (0x1F300 <= cp <= 0x1FAFF) or (0x2600 <= cp <= 0x27BF) or (0xFE00 <= cp <= 0xFE0F)
    result = []
    prev_emoji = False
    for ch in text:
        if is_emoji(ch):
            if not prev_emoji:
                result.append(ch)
            prev_emoji = True
        else:
            prev_emoji = False
            result.append(ch)
    # Убираем эмодзи в начале каждой строки (кроме первого)
    lines = ''.join(result).split('\n')
    cleaned = []
    for line in lines:
        stripped = line.lstrip()
        # Удаляем ведущие эмодзи-маркеры типа "🔸 текст" -> "текст"
        stripped = re.sub(r'^[\U0001F300-\U0001FAFF\U00002600-\U000027BF]+\s*', '', stripped)
        # Восстанавливаем отступ
        indent = len(line) - len(line.lstrip())
        cleaned.append(' ' * indent + stripped)
    return '\n'.join(cleaned)



def days_left_str(deadline: str, user_id: Optional[int] = None) -> str:
    try:
        dl = datetime.strptime(deadline, '%Y-%m-%d').date()
        today = user_today_date(user_id) if user_id is not None else datetime.now().date()
        diff = (dl - today).days
        if diff < 0:
            return "просрочена!"
        elif diff == 0:
            return "сегодня!"
        elif diff == 1:
            return "завтра"
        else:
            return f"{diff} дн."
    except:
        return ""



def format_repeat_days(repeat_days: str) -> str:
    try:
        days = [WEEKDAY_NAMES[int(d)] for d in repeat_days.split(',') if d.strip().isdigit()]
        return ", ".join(days)
    except:
        return ""
