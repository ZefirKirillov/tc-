import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor


async def run_in_thread(func, *args, **kwargs):
    """Запускает синхронную функцию в пуле потоков, не блокируя event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))



async def iterate_in_thread(gen_func, *args, **kwargs):
    """Прогоняет синхронный генератор в пуле потоков и отдаёт его элементы
    асинхронно, по мере появления (для стриминга ответов ИИ)."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    done = object()

    def _run():
        try:
            for item in gen_func(*args, **kwargs):
                loop.call_soon_threadsafe(queue.put_nowait, (item, None))
        except BaseException as e:
            loop.call_soon_threadsafe(queue.put_nowait, (done, e))
        else:
            loop.call_soon_threadsafe(queue.put_nowait, (done, None))

    loop.run_in_executor(None, _run)
    while True:
        item, error = await queue.get()
        if item is done:
            if error is not None:
                raise error
            return
        yield item



_db_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="db")



async def run_db(func, *args, **kwargs):
    """Запускает синхронную DB-функцию в выделенном пуле потоков, не блокируя event loop.
    Сохраняет тот же интерфейс, что и оригинальная синхронная функция."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_db_executor, functools.partial(func, *args, **kwargs))
