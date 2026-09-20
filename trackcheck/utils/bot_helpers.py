import asyncio
from typing import Optional

from aiogram import Bot

from trackcheck.runtime import user_temp_messages


async def delete_message_safe(bot: Bot, chat_id: int, message_id: Optional[int]):
    if message_id:
        try:
            await bot.delete_message(chat_id, message_id)
        except Exception as e:
            print(f"[BOT] Ошибка удаления сообщения {message_id}: {e}")



async def delete_message_after_delay(bot: Bot, chat_id: int, message_id: Optional[int], delay: int = 10):
    await asyncio.sleep(delay)
    await delete_message_safe(bot, chat_id, message_id)



async def delete_temp_messages(bot: Bot, user_id: int, chat_id: int, keep_ai: bool = True):
    """Удаляет все временные сообщения кроме явно сохранённых."""
    temps = user_temp_messages.get(user_id, {})
    if not temps:
        return
    # Ключи, которые НЕ удаляем: ИИ сообщения, фото анализа, замеры % жира
    keys_to_preserve = set()
    if keep_ai:
        keys_to_preserve.update({'ai_response', 'ai_advisor'})
    keys_to_preserve.update({'photo_analysis_result', 'photo_user', 'body_fat_measurements', 'body_fat_result'})

    keys_to_delete = []
    for key, msg_id in list(temps.items()):
        if key in keys_to_preserve:
            continue
        keys_to_delete.append(key)
        await delete_message_safe(bot, chat_id, msg_id)
    for key in keys_to_delete:
        del temps[key]



async def send_spark_animation(bot: Bot, chat_id: int, text: str):
    spark_msg = await bot.send_message(chat_id, "✨")
    text_msg = await bot.send_message(chat_id, text)
    await asyncio.sleep(3)
    await delete_message_safe(bot, chat_id, spark_msg.message_id)
    await delete_message_safe(bot, chat_id, text_msg.message_id)



async def send_temp_message(bot: Bot, chat_id: int, text: str, delay: int = 3):
    msg = await bot.send_message(chat_id, text)
    await asyncio.sleep(delay)
    await delete_message_safe(bot, chat_id, msg.message_id)
