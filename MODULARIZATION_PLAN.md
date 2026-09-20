# MODULARIZATION_PLAN.md — TrackCheck

Refactor of the monolithic `ctx.py` (8368 lines) into a `trackcheck/` package.
`ctx.py` stays as the entry point: `python ctx.py` must still start the bot.

## 1. Goals & constraints

- **No behaviour changes.** Every command, `callback_data`, FSM state, DB
  table/schema, env var, config variable and message text is preserved verbatim.
- **No code removal.** Several symbols are defined but never used in the
  original (`bot_instance`, `generate_proactive_ai_message`,
  `generate_weekly_report`, `WEEKDAY_SHORT`, `format_goal_button_text`,
  `workout_ai_main_keyboard`, `wp_monthly_review_keyboard`,
  `photo_analysis_back_keyboard`, `delete_welcome_after_delay` is used,
  `ensure_back_keyboard`/`BackKeyboardMiddleware` are no-ops). All of them are
  kept (rule 6) and their call sites/registration points are kept too.
- **Single shared `Router`.** aiogram dispatches the *first* matching handler,
  so handler registration order is observable. To guarantee identical ordering
  the whole bot keeps ONE `Router` instance, created in
  `trackcheck/handlers/__init__.py`, and handler sub-modules are imported there
  in the same top-to-bottom order as the original file. Order-sensitive pairs
  that are preserved:
  - `universal_back` (msg `F.text == BACK_BUTTON_TEXT`, orig line 787) must be
    registered before state text handlers (`process_mood_text` 3604,
    `ws_exercise_text_input` 5175, …) → `handlers/navigation.py` is imported
    first.
  - `workout_add_choose_category` (4113) before `workout_charts_choose_category`
    (6506) — same `w_add_cat_` filter; the first one delegates to the second
    when `workout_charts_mode` is set. Same for `w_add_ex_` (4130 before 6524).
    Both stay in `handlers/workouts.py` in original order.
  - `diet_cancel_food` (6773, state-filtered) before the unfiltered
    `food_cancel` (7061) — both in `handlers/food.py` in original order.
- **Async stays async.** All Telegram + DB operations keep their async wrappers
  (`run_in_thread` / `run_db`); nothing is converted to sync or vice-versa.

## 2. Dependency rules (acyclic, enforced by an import-graph check)

```
config                  (constants only; os + optional libsql)
states/*                (aiogram State groups only)
runtime                 (in-memory process globals; no trackcheck imports)
database/connection     -> config
utils/concurrency       (thread pools)
utils/dates             -> database.connection, config      (owns tz cache)
utils/formatting        -> utils/dates
utils/validation        (pure)
utils/bot_helpers       -> runtime
utils/logging           -> database.connection, config
database/repositories   -> database.connection, config, utils/dates,
                           services/gamification_service (rank math only)
services/gamification   -> config
services/ai_service     -> database/repositories, utils/formatting, config
services/tracker_service-> database/repositories, services/ai_service, config
services/workout_service-> database/repositories, config
services/stats_service  (plotly)
services/chart_service  (plotly)
keyboards/*             -> config, utils/formatting, utils/dates
handlers/*              -> everything above + screens (screens is imported by
                           handlers/navigation only through render_screen)
screens                 -> handlers/* (menu/screen render funcs), keyboards,
                           services, states, runtime
handlers/__init__       -> handlers/* (creates the single Router, registers the
                           no-op BackKeyboardMiddleware, imports sub-modules in
                           original file order)
app                     -> handlers (router), database/connection, utils/logging,
                           services/tracker_service, config, runtime
ctx.py                  -> app.main
```

No module imports a package that (transitively) imports it back; verified with
a DAG check (see §6). `handlers/navigation.py` calls `screens.render_screen`;
`screens` never imports `handlers/navigation`.

## 3. Old → new location map

### config.py
`BOT_TOKEN`, `GOOGLE_API_KEY`, libsql try-import, `DB_PATH`,
`TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `USE_TURSO`, `RANKS`,
`MAX_SPARKS_PER_DAY`, `SPARK_FOR_CATEGORIES`, `SPARK_FOR_WORKOUT`,
`BACK_BUTTON_TEXT`, `BACK_BUTTON_CALLBACK`, `DEFAULT_TIMEZONE`,
`RUSSIAN_TIMEZONES`, `WEEKDAY_NAMES`, `WEEKDAY_RU`, `WEEKDAY_SHORT`,
`WEEKDAY_KEY`, `WEEKDAY_FROM_KEY`.

### runtime.py
`user_last_menu`, `user_temp_messages`, `user_history_page`,
`user_food_history_page`, `user_welcome_message`, `user_nav`, `scheduler`,
`bot_instance`, `nav_push`, `nav_current`, `nav_pop`.

### database/connection.py
`_CompatRow`, `_CompatCursor`, `Database`, `db`, `init_db`.

### database/repositories.py
users/streaks/ratings: `save_user_settings`, `get_user_name`(+`_name_cache`),
`update_streak`, `get_streak`, `save_rating`, `get_ratings`,
`get_daily_ratings`, `get_today_ratings`, `get_yesterday_ratings`,
`check_all_categories_completed`, `manual_categories_completed`.
gamification DB: `_fetch_rank_data`, `get_or_create_rank_data`,
`_deduct_spark_for_skip`, `add_spark`.
workout counters: `get_or_create_workout_data`, `set_workout_goal`,
`add_workout`, `change_workout_goal`.
diet: `save_diet_profile`, `get_diet_profile`, `save_food_log`,
`get_today_calories`, `get_today_food_log`, `save_weight_log`, `get_last_weight`,
`save_body_fat`, `add_my_food`, `get_my_foods`, `save_last_ai_answer`,
`get_last_ai_answer`, `calculate_bmr`, `calculate_tdee`,
`calculate_daily_calories`.
tasks: `get_tasks_for_today`, `get_all_active_tasks`, `get_urgent_tasks_for_menu`,
`complete_task`, `delete_task`, `add_task`.
AI plan/sessions: `get_ai_plan`, `save_ai_plan`, `delete_all_workout_data`,
`get_current_week_session_key`, `get_today_plan`, `get_today_session`,
`create_today_session`, `get_session_exercise_logs`, `get_previous_same_session`,
`get_next_training_day`, `get_weekly_workout_progress`, `update_plan_json`,
`update_session_exercise_plan`.

### services/gamification_service.py
`get_current_rank`, `get_sparks_for_next_rank`, `get_rank_emoji`,
`get_rank_name`, `get_rank_motivation`.

### services/ai_service.py
`strip_markdown` (moved here from the “formatting” area: it is an AI-output
cleaner, but kept importable from `utils.formatting` too — no, see §5), the
Gemini layer: `gemini_generate`, `gemini_generate_json`, `gemini_generate_rating`,
`analyze_food_photo`, `_parse_json_response`, `gemini_generate_plan`,
`_fallback_parse_plan`, `gemini_parse_manual_plan`, `gemini_edit_plan`,
`gemini_parse_exercise_result`, `gemini_session_feedback`,
`gemini_adapt_next_session`, `gemini_monthly_review`, plus context assembly
`get_user_stats_for_ai`, `get_full_context_for_ai`, `analyze_low_rating`,
`generate_proactive_ai_message`, `generate_weekly_report` (last three are dead
code in the original — kept).

### services/tracker_service.py
`sync_diet_rating_for_today`, `sync_activity_rating_for_today`,
`finalize_daily_ratings_for_timezone`.

### services/workout_service.py
`format_plan_for_display`, `format_exercise_card`, `_format_full_plan`,
`_format_session_detail`, `apply_monthly_changes`.

### services/stats_service.py
`create_line_chart`.

### services/chart_service.py
`build_workout_progress_chart`, `build_diet_chart` — extracted verbatim from the
inline plotly code that lived inside `workout_charts_generate` and
`diet_charts_reply`; same figures, same file names, same `scale=2`, callers
still send the photo and `os.remove` the file (identical to `create_line_chart`
which already worked that way).

### utils/
- `concurrency.py`: `_db_executor`, `run_in_thread`, `run_db`.
- `dates.py`: `_tz_cache`, `get_user_timezone`, `set_user_timezone`,
  `_resolve_tz`, `user_now`, `user_today_str`, `user_today_date`, `user_weekday`.
- `formatting.py`: `create_new_progress_bar`, `create_short_progress_bar`,
  `create_workout_progress_bar`, `get_time_greeting`, `days_left_str`,
  `format_repeat_days`.
- `validation.py`: `parse_reps_input`, `format_goal_button_text`.
- `bot_helpers.py` (extra, justified by real code): `delete_message_safe`,
  `delete_message_after_delay`, `delete_temp_messages`, `send_spark_animation`,
  `send_temp_message`.
- `logging.py`: `log_db_persistence_diagnostics`, `log_ratings_ai_diagnostics`.
- `strip_markdown` lives in `utils/formatting.py` (it is a text cleaner) and is
  re-exported by `services/ai_service.py` (`from ..utils.formatting import
  strip_markdown`) — no duplication, single definition.

### keyboards/
- `common.py`: `_back_button_row`, `_has_back_button`, `with_back_kb`,
  `back_reply_keyboard`, `ensure_back_keyboard`, `BackKeyboardMiddleware`,
  `retry_ai_keyboard`, `timezone_picker_keyboard`.
- `dashboard.py`: `main_menu_keyboard`, `urgent_tasks_keyboard`.
- `categories.py`: `reflection_keyboard`, `rating_keyboard`,
  `low_rating_keyboard`.
- `ai.py` (extra): `ai_reply_keyboard`, `photo_analysis_cancel_keyboard`,
  `photo_analysis_back_keyboard`.
- `workouts.py`: all `workout_*`, `wp_*`, `ws_*` keyboards +
  `workout_ai_main_keyboard`, `wp_monthly_review_keyboard`.
- `stats.py`: `stats_keyboard`, `rank_back_keyboard`.
- `food.py` (extra): `diet_menu_reply_keyboard`, `meal_type_keyboard`,
  `meal_chosen_keyboard`, `save_food_keyboard`, `my_foods_keyboard`,
  `gender_keyboard`, `activity_keyboard`, `goal_keyboard`, `diet_confirm_keyboard`,
  `diet_confirm_food_keyboard`, `food_add_more_keyboard`, `food_cancel_keyboard`.
- `tasks.py` (extra): `tasks_menu_keyboard`, `tasks_confirm_keyboard`,
  `task_repeat_keyboard`, `task_days_keyboard`, `task_priority_keyboard`,
  `task_deadline_keyboard`.

### states/
- `category.py`: `RatingState`.
- `workout.py`: `WorkoutState`, `AIPlanState`, `WorkoutSessionState`.
- `food.py`: `DietState`.
- `settings.py`: `AIAdvisorState`, `TaskState` (misc FSM groups).

### handlers/
- `navigation.py`: `universal_back`, `universal_back_inline`.
- `dashboard.py`: `format_main_menu`, `send_main_menu`, `back_to_main_callback`.
- `categories.py`: `show_reflection_menu`, `handle_reflection`, `handle_category`,
  `process_mood_text`, `process_rating`, `analyze_low_rating_handler`,
  `skip_analysis`.
- `ai.py`: `handle_ai`, `wp_edit_retry`, `handle_ai_advice`, `process_ai_question`,
  `show_last_ai`, `retry_ai_action` and every `_retry_*` helper
  (`_retry_mood_rating`, `_retry_ai_advice`, `_retry_ai_question`,
  `_retry_generate_plan`, `_retry_low_rating`, `_retry_food_calories`,
  `_retry_photo_analysis`, `_retry_food_photo`, `_retry_manual_plan`,
  `_retry_monthly_review`, `_retry_session_feedback`).
- `start.py`: `cmd_start`, `delete_welcome_after_delay`, `handle_start_button`,
  `_start_onboarding`, `handle_timezone_choice`, `cmd_timezone`.
- `workouts.py`: photo-analysis handlers (`handle_photo_analysis_start`,
  `analyze_photo`, `photo_analysis_cancel`, `photo_analysis_back`,
  `photo_timeout`) + the whole workout section (`show_workout_main_menu` …
  `workout_show_goal`, incl. AI-plan wizard, session flow, category/exercise CRUD,
  history, charts, `_format_full_plan` lives in workout_service).
- `food.py`: the whole diet section (`handle_diet` … `diet_step_restart`).
- `stats.py`: `_show_stats_choice`, `handle_stats`, `show_stats`, `_show_rank`,
  `handle_rank`.
- `settings.py`: tasks (`show_tasks_menu` … `_save_task`).

### screens.py
`render_screen`, `_screen_send`, every `_screen_*`, `WEX_DAY_NAMES`,
`WEX_DAY_ORDER`, `_wex_day_buttons`, `_wex_day_exercises`, `SCREEN_RENDER`
registry (same keys, `wp_review_decline_prompt` → `_screen_workout_today`
preserved).

### app.py
`main()` — identical boot sequence (`init_db`, both diagnostics, Dispatcher +
`MemoryStorage`, single router, `AsyncIOScheduler` with one cron job per
`RUSSIAN_TIMEZONES` at 23:55 calling `finalize_daily_ratings_for_timezone`,
`delete_webhook(drop_pending_updates=True)`, polling, SIGINT/SIGTERM handling,
graceful shutdown).

### ctx.py
Bootstrap only: `import asyncio`, `from trackcheck.app import main`,
`if __name__ == "__main__": asyncio.run(main())`.

## 4. Deviations from the suggested target tree (documented)

- Extra modules created because the suggested list had no home for real code:
  `runtime.py`, `screens.py`, `utils/concurrency.py`, `utils/bot_helpers.py`,
  `keyboards/ai.py`, `keyboards/food.py`, `keyboards/tasks.py`.
- **`services/reminder_service.py` is intentionally NOT created**: the original
  has a `reminders` table and an `apscheduler` dependency, but zero reminder
  logic (the scheduler’s only jobs are the daily rating-finalize cron jobs).
  Creating the file would violate “do not create empty files”.
- `services/stats_service.py` holds `create_line_chart`; the stats *handlers*
  stay in `handlers/stats.py`.
- `strip_markdown` is defined once in `utils/formatting.py`.

## 5. Risks / ambiguous items

1. **Handler ordering** is observable (see §1). Mitigated by one shared Router
   + fixed import order; manually re-checked against the original line order.
2. **`wp_notes_skip` reuse** — the “Пропустить →” button on the
   delete-exercise confirmation (orig 6130) uses `callback_data="wp_notes_skip"`
   whose only handler is state-filtered on `AIPlanState.entering_extra_notes`,
   so in the original that button is a no-op (unanswered callback). Behaviour
   preserved as-is; not “fixed”.
3. **Duplicate `w_add_cat_` / `w_add_ex_` handlers** — the second registration
   is unreachable by the dispatcher and is only ever called as a plain function
   from the first handler. Both kept and order preserved.
4. **Mid-file imports in the original** (`import json` at 1628,
   `ThreadPoolExecutor` at 1844, local `import functools/traceback/re`) are
   hoisted to module tops; semantics unchanged.
5. **No runtime verification possible here** — aiogram/apscheduler/plotly/
   google-genai/libsql are **not installed** in this environment and there is no
   `pip`. `python -c "import ctx"` fails on the *original* file too (first line
   `from aiogram import Router`). Verification is therefore:
   `python -m compileall .`, `python -m tabnanny ctx.py`, plus a custom
   **AST undefined-name checker** over every new module (catches any symbol used
   but neither defined nor imported) and an **import-graph DAG check** (catches
   circular imports). The bot itself must be started by the user where deps
   exist (see §7).
6. **`scheduler` global** — original used `global scheduler` inside `main()`;
   now `app.main` sets `trackcheck.runtime.scheduler`. Only `main()` reads it.
7. **`bot_instance`** is never assigned after initialisation; kept as-is.

## 6. Final directory tree

```
ctx.py                      (bootstrap; entry point: python ctx.py)
MODULARIZATION_PLAN.md
requirements.txt            (unchanged)
runtime.txt                 (unchanged)
trackcheck/
├── __init__.py
├── app.py
├── config.py
├── runtime.py
├── screens.py
├── database/
│   ├── __init__.py
│   ├── connection.py
│   └── repositories.py
├── handlers/
│   ├── __init__.py         (single Router + middleware + sub-module import order)
│   ├── navigation.py
│   ├── dashboard.py
│   ├── categories.py
│   ├── ai.py
│   ├── start.py
│   ├── workouts.py
│   ├── food.py
│   ├── stats.py
│   └── settings.py
├── keyboards/
│   ├── __init__.py
│   ├── common.py
│   ├── dashboard.py
│   ├── categories.py
│   ├── ai.py
│   ├── workouts.py
│   ├── stats.py
│   ├── food.py
│   └── tasks.py
├── services/
│   ├── __init__.py
│   ├── gamification_service.py
│   ├── ai_service.py
│   ├── tracker_service.py
│   ├── workout_service.py
│   ├── stats_service.py
│   └── chart_service.py
├── states/
│   ├── __init__.py
│   ├── category.py
│   ├── workout.py
│   ├── food.py
│   └── settings.py
└── utils/
    ├── __init__.py
    ├── concurrency.py
    ├── dates.py
    ├── formatting.py
    ├── validation.py
    ├── bot_helpers.py
    └── logging.py
```

## 7. How to run after the refactor

```
python ctx.py
```

Exactly as before. All env vars unchanged (`BOT_TOKEN`, `GOOGLE_API_KEY`,
optional `GOOGLE_API_KEY_RATINGS`/`GEMINI_API_KEY_RATINGS`, `DB_PATH`,
`TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`). Requirements and hosting config are
untouched.
