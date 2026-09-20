from datetime import datetime

import plotly.graph_objects as go
from plotly.subplots import make_subplots


def build_workout_progress_chart(user_id: int, rows: list, ex_type: str) -> str:
    dates = [datetime.strptime(r[0], '%Y-%m-%d').strftime('%d.%m') for r in rows]
    if ex_type == 'strength':
        avg_reps = []
        weights = []
        for r in rows:
            reps_str = r[2]
            reps_list = [int(x) for x in reps_str.split(',')] if reps_str else []
            avg = sum(reps_list)/len(reps_list) if reps_list else 0
            avg_reps.append(avg)
            weights.append(r[3] or 0)
        fig = make_subplots(rows=2, cols=1, subplot_titles=("Средние повторения", "Вес (кг)"))
        fig.add_trace(go.Scatter(x=dates, y=avg_reps, mode='lines+markers', name='Повторения'), row=1, col=1)
        fig.add_trace(go.Scatter(x=dates, y=weights, mode='lines+markers', name='Вес'), row=2, col=1)
        fig.update_layout(title="Прогресс упражнения", height=600, showlegend=False, template='plotly_dark')
    else:
        distances = [r[4] or 0 for r in rows]
        durations = [r[5] or 0 for r in rows]
        pace = [durations[i]/distances[i] if distances[i] else 0 for i in range(len(rows))]
        fig = make_subplots(rows=3, cols=1, subplot_titles=("Дистанция (км)", "Время (мин)", "Темп (мин/км)"))
        fig.add_trace(go.Scatter(x=dates, y=distances, mode='lines+markers', name='Дистанция'), row=1, col=1)
        fig.add_trace(go.Scatter(x=dates, y=durations, mode='lines+markers', name='Время'), row=2, col=1)
        fig.add_trace(go.Scatter(x=dates, y=pace, mode='lines+markers', name='Темп'), row=3, col=1)
        fig.update_layout(title="Прогресс кардио", height=800, showlegend=False, template='plotly_dark')

    chart_path = f"workout_chart_{user_id}.png"
    fig.write_image(chart_path, scale=2)
    return chart_path


def build_diet_chart(user_id: int, weight_rows: list, fat_rows: list) -> str:
    if len(weight_rows) < 2 and len(fat_rows) < 2:
        return None
    dates_weight = [datetime.strptime(r[0], '%Y-%m-%d').strftime('%d.%m') for r in weight_rows]
    weights = [r[1] for r in weight_rows]
    dates_fat = [datetime.strptime(r[0], '%Y-%m-%d').strftime('%d.%m') for r in fat_rows]
    fats = [r[1] for r in fat_rows]

    fig = make_subplots(rows=2, cols=1, subplot_titles=("Вес (кг)", "Процент жира"))
    if dates_weight:
        fig.add_trace(go.Scatter(x=dates_weight, y=weights, mode='lines+markers', name='Вес'), row=1, col=1)
    if dates_fat:
        fig.add_trace(go.Scatter(x=dates_fat, y=fats, mode='lines+markers', name='% жира'), row=2, col=1)
    fig.update_layout(title="Динамика веса и % жира", height=600, showlegend=False, template='plotly_dark')

    chart_path = f"diet_chart_{user_id}.png"
    fig.write_image(chart_path, scale=2)
    return chart_path
