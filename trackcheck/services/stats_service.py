from collections import defaultdict
from datetime import datetime

import plotly.graph_objects as go


def create_line_chart(daily_data: list, user_id: int, days: int = 7) -> str:
    """Строит линейный график динамики оценок рефлексии по категориям за период
    (данные из get_daily_ratings: строки day_date/category/rating) и сохраняет
    как PNG. Возвращает путь к файлу — вызывающий код сам удаляет его после
    отправки, как и другие графики в этом файле (см. diet_chart_*)."""
    by_category = defaultdict(dict)
    seen_dates = set()
    all_dates = []
    for row in daily_data:
        date_str, category, rating = row[0], row[1], row[2]
        by_category[category][date_str] = rating
        if date_str not in seen_dates:
            seen_dates.add(date_str)
            all_dates.append(date_str)
    all_dates.sort()
    x_labels = [datetime.strptime(d, '%Y-%m-%d').strftime('%d.%m') for d in all_dates]

    category_labels = {
        'сон': '😴 Сон', 'еда': '🍽 Еда', 'активность': '💪 Активность',
        'зависание': '🎮 Зависание', 'настрой': '🎯 Настрой',
    }

    fig = go.Figure()
    for cat in ('сон', 'еда', 'активность', 'зависание', 'настрой'):
        if cat not in by_category:
            continue
        y = [by_category[cat].get(d) for d in all_dates]
        fig.add_trace(go.Scatter(
            x=x_labels, y=y, mode='lines+markers',
            name=category_labels.get(cat, cat), connectgaps=False
        ))
    fig.update_layout(
        title=f"Динамика рефлексии за {'неделю' if days <= 7 else 'месяц'}",
        yaxis=dict(range=[0, 10.5], title="Оценка"),
        height=500, template='plotly_dark'
    )

    chart_path = f"reflection_chart_{user_id}.png"
    fig.write_image(chart_path, scale=2)
    return chart_path
