import time
import sys
import inspect
import threading
from functools import wraps
from typing import Union, Callable, Any


FACES = ["(✿◕‿◕)", "(✿-‿-)", "(✿-_-)"]
CLOCKS = ['◴','◵','◶','◷']


def _cursed_logic(cursed: bool, index: int, face_index: int):
    """Whether or not to show the timer and face animations"""
    anime_str = f"{FACES[face_index]} {CLOCKS[index]} " if cursed else ''
    timer_wait = 0.2 if cursed else 0.1
    return timer_wait, anime_str


def _return_indices(cursed: bool, elapsed: float, index: int, face_index: int):
    """Cycle through face and clock animations"""
    if cursed:
        index = (index + 1) % len(CLOCKS)
        if elapsed < 60:
            face_index = 0
        elif elapsed >= 60 and elapsed < 120:
            face_index = 1
        else:
            face_index = 2
    return index, face_index


def _display_exec_time(start_time: float, cursed: bool = False):
    """Display a funny face depending on how a function took to run."""
    final_time = time.time() - start_time
    if cursed:
        if final_time < 60:
            exec_face = "(✿◠‿◠)"
        elif final_time >= 60 and final_time < 120:
            exec_face = "(ಠ_ಠ)"
        else:
            exec_face = "(╯°□°)╯︵ ┻━┻"
        print(f'\n{exec_face} Total execution time: {final_time:.2f} seconds')
    else:
        print(f'\nTotal execution time: {final_time:.2f} seconds')


def _show_clock(start_time: float, timer_wait: float, anime_str: str, cursed: bool, index: int, face_index: int):
    """Show and update the clock"""
    elapsed = time.time() - start_time
    print(f'\r{anime_str}Running time: {elapsed:.2f} seconds', end='')
    sys.stdout.write('\r')
    sys.stdout.write(f'{anime_str}Running time: {elapsed:.2f} seconds')
    sys.stdout.flush()
    time.sleep(timer_wait)
    index, face_index = _return_indices(cursed, elapsed, index, face_index)
    return index, face_index


def _update_display_thread(stop_flag: dict, start_time: float, cursed: bool = False):
    """
    Thread function that updates the display with a talking face animation and running time.
    """
    index = 0
    face_index = 0
    timer_wait, anime_str = _cursed_logic(cursed, index, face_index)

    while stop_flag['running']:
        index, face_index = _show_clock(start_time, timer_wait, anime_str, cursed, index, face_index)


def stopwatch_decorator(func: Union[Callable, Callable[..., Any]], cursed: bool = False):
    """
    A decorator that measures and displays execution time for both sync and async functions.
    Updates the console with running time during execution.
    """
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        start_time = time.time()
        stop_flag = {'running': True}  # Using a dict as a mutable object

        # Start display thread
        display_thread = threading.Thread(target=_update_display_thread, args=(stop_flag, start_time, cursed))
        display_thread.start()

        try:
            result = await func(*args, **kwargs)
            return result
        finally:
            # Clean up
            stop_flag['running'] = False  # Modify the mutable object
            display_thread.join()
            _display_exec_time(start_time, cursed=cursed)

    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        start_time = time.time()
        stop_flag = {'running': True}  # Using a dict as a mutable object

        # Start display thread
        display_thread = threading.Thread(target=_update_display_thread, args=(stop_flag, start_time, cursed))
        display_thread.start()

        try:
            result = func(*args, **kwargs)
            return result
        finally:
            # Clean up
            stop_flag['running'] = False  # Modify the mutable object
            display_thread.join()
            _display_exec_time(start_time, cursed=cursed)  # Fixed: Added cursed parameter

    # Determine if the function is async or sync
    if inspect.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


def stopwatch(func, *args, cursed: bool = False, **kwargs):
    """
    Time a synchronous function and display running time.
    
    Args:
        func: The synchronous function to time
        *args: Arguments to pass to the function
        **kwargs: Keyword arguments to pass to the function
    """
    start_time = time.time()
    stop_flag = {'running': True}

    # Start display thread
    display_thread = threading.Thread(target=_update_display_thread, args=(stop_flag, start_time, cursed))
    display_thread.start()

    try:
        result = func(*args, **kwargs)
        return result
    finally:
        stop_flag['running'] = False
        display_thread.join()
        _display_exec_time(start_time, cursed=cursed)  # Fixed: Added cursed parameter


async def async_stopwatch(func, *args, cursed: bool = False, **kwargs):
    """
    Time an asynchronous function and display running time.
    
    Args:
        func: The async function to time
        *args: Arguments to pass to the function
        **kwargs: Keyword arguments to pass to the function
    """
    start_time = time.time()
    stop_flag = {'running': True}

    # Start display thread
    display_thread = threading.Thread(target=_update_display_thread, args=(stop_flag, start_time, cursed))
    display_thread.start()

    try:
        result = await func(*args, **kwargs)
        return result
    finally:
        stop_flag['running'] = False
        display_thread.join()
        _display_exec_time(start_time, cursed=cursed)