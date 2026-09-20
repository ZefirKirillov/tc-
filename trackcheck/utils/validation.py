from typing import List, Tuple


def parse_reps_input(reps_input: str) -> Tuple[int, List[int]]:
    reps_input = reps_input.strip()
    if 'x' in reps_input.lower():
        parts = reps_input.lower().split('x')
        if len(parts) == 2:
            try:
                sets = int(parts[0])
                reps_per_set = int(parts[1])
                return sets, [reps_per_set] * sets
            except ValueError:
                pass
    if ' ' in reps_input:
        parts = reps_input.split()
        try:
            reps_list = [int(p) for p in parts]
            return len(reps_list), reps_list
        except ValueError:
            pass
    if ',' in reps_input:
        parts = reps_input.split(',')
        try:
            reps_list = [int(p.strip()) for p in parts]
            return len(reps_list), reps_list
        except ValueError:
            pass
    try:
        reps = int(reps_input)
        return 1, [reps]
    except ValueError:
        pass
    raise ValueError("Неверный формат")



def format_goal_button_text(exercise: dict) -> str:
    if exercise.get('ex_type') == 'strength':
        target_sets = exercise.get('target_sets')
        target_reps = exercise.get('target_reps')
        target_weight = exercise.get('target_weight')
        if target_sets and target_reps:
            return f"🎯 Цель достигнута ({target_sets}х{target_reps}{f' +{target_weight}кг' if target_weight else ''})"
    else:
        target_distance = exercise.get('target_distance')
        target_duration = exercise.get('target_duration')
        if target_distance and target_duration:
            return f"🎯 Цель достигнута ({target_distance}км / {target_duration}мин)"
    return None
