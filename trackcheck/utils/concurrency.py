import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor


async def run_in_thread(func, *args, **kwargs):
    """Запускает синхронную функцию в пуле потоков, не блокируя event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))



_db_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="db")



async def run_db(func, *args, **kwargs):
    """Запускает синхронную DB-функцию в выделенном пуле потоков, не блокируя event loop.
    Сохраняет тот же интерфейс, что и оригинальная синхронная функция."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_db_executor, functools.partial(func, *args, **kwargs))
