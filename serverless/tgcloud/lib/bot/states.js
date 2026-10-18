// trackcheck/states/*.py — same "Group:name" strings aiogram used.

function group(name, states) {
  return Object.fromEntries(states.map(s => [s, `${name}:${s}`]))
}

export const RatingState = group('RatingState', ['waiting_for_rating', 'waiting_for_mood_text'])

export const DietState = group('DietState', [
  'weight', 'height', 'age', 'gender', 'activity', 'goal', 'target_weight', 'target_days', 'confirm',
  'meal_type', 'food_description', 'manual_calories', 'food_confirm', 'new_food_name',
  'new_food_calories', 'log_weight', 'body_fat_measurements',
])

export const AIAdvisorState = group('AIAdvisorState', ['waiting_for_question'])

export const TaskState = group('TaskState', [
  'entering_title', 'choosing_repeat', 'choosing_days', 'choosing_priority', 'choosing_deadline', 'entering_deadline',
])

export const WorkoutState = group('WorkoutState', [
  'waiting_for_goal', 'choosing_category', 'choosing_exercise', 'entering_reps', 'entering_weight',
  'entering_distance', 'entering_duration', 'confirm_continue', 'creating_category', 'renaming_category',
  'deleting_category_confirm', 'creating_exercise', 'renaming_exercise', 'deleting_exercise_confirm',
  'setting_goal_type', 'setting_strength_goal', 'setting_weight_increment', 'setting_cardio_goal',
  'current_cat_id', 'current_ex_id',
])

export const AIPlanState = group('AIPlanState', [
  'choosing_mode', 'choosing_goal', 'choosing_level', 'choosing_days_count', 'reviewing_plan',
  'editing_plan', 'entering_manual_plan', 'entering_extra_notes',
])

export const WorkoutSessionState = group('WorkoutSessionState', [
  'viewing_plan', 'in_exercise', 'entering_result', 'skipping_day', 'monthly_review', 'free_logging',
  'replacing_exercise', 'raising_weight',
])
