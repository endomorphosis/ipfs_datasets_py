# AnyIO Quick Reference for Processors

**Purpose:** Quick lookup guide for migrating asyncio → anyio in processors  
**Target Audience:** Developers working on Phase 1 of refactoring  
**Last Updated:** 2026-02-16

---

## Why AnyIO?

✅ **Cross-platform compatibility** - Works with asyncio, trio, and curio  
✅ **Better structured concurrency** - Task groups prevent common async bugs  
✅ **Simpler API** - Less boilerplate, cleaner code  
✅ **Type safety** - Better type hints and static analysis  
✅ **Modern patterns** - Encourages best practices like timeouts and cancellation  

---

## Quick Migration Table

| What You Want | asyncio (OLD ❌) | anyio (NEW ✅) |
|---------------|------------------|----------------|
| Sleep | `await asyncio.sleep(1)` | `await anyio.sleep(1)` |
| Run tasks concurrently | `await asyncio.gather(t1, t2)` | See Task Groups below |
| Timeout | `await asyncio.wait_for(coro, 30)` | `with anyio.fail_after(30):` |
| Run in thread | `loop.run_in_executor(None, func)` | `await anyio.to_thread.run_sync(func)` |
| Locks | `asyncio.Lock()` | `anyio.Lock()` |
| Events | `asyncio.Event()` | `anyio.Event()` |
| Semaphore | `asyncio.Semaphore(10)` | `anyio.Semaphore(10)` |
| Queue | `asyncio.Queue()` | See Memory Streams below |
| Run async code | `asyncio.run(main())` | `anyio.run(main)` |

---

## Pattern 1: Task Groups (Most Important!)

### ❌ OLD (asyncio.gather)
```python
import asyncio

async def process_batch(items):
    tasks = [process_item(item) for item in items]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results
```

**Problems:**
- No structured concurrency - tasks may leak
- Harder to cancel properly
- Exception handling is tricky
- Can't easily share state between tasks

### ✅ NEW (anyio task groups)
```python
import anyio

async def process_batch(items):
    results = []
    
    async with anyio.create_task_group() as tg:
        for item in items:
            tg.start_soon(process_and_collect, item, results)
    
    # All tasks guaranteed to complete when exiting context
    return results

async def process_and_collect(item, results):
    result = await process_item(item)
    results.append(result)
```

**Benefits:**
- ✅ Structured concurrency - tasks cleaned up automatically
- ✅ Easy cancellation - cancel the group, all tasks cancel
- ✅ Clear scope - tasks can't outlive the group
- ✅ Better error handling

---

## Pattern 2: Timeouts

### ❌ OLD (asyncio.wait_for)
```python
import asyncio

async def fetch_with_timeout():
    try:
        result = await asyncio.wait_for(fetch_data(), timeout=30.0)
        return result
    except asyncio.TimeoutError:
        print("Timed out!")
        return None
```

### ✅ NEW (anyio.fail_after)
```python
import anyio

async def fetch_with_timeout():
    try:
        with anyio.fail_after(30):  # Cleaner!
            result = await fetch_data()
            return result
    except TimeoutError:  # Standard exception
        print("Timed out!")
        return None
```

**Benefits:**
- ✅ Context manager is more intuitive
- ✅ Uses standard TimeoutError exception
- ✅ Can wrap multiple operations

---

## Pattern 3: Concurrency Limiting

### ❌ OLD (asyncio.Semaphore)
```python
import asyncio

semaphore = asyncio.Semaphore(10)

async def limited_operation():
    async with semaphore:
        return await expensive_operation()
```

### ✅ NEW (anyio.CapacityLimiter)
```python
import anyio

limiter = anyio.CapacityLimiter(10)

async def limited_operation():
    async with limiter:
        return await expensive_operation()
```

**Note:** API is nearly identical, but CapacityLimiter has better semantics and can be shared across backends.

---

## Pattern 4: Running Blocking Functions

### ❌ OLD (loop.run_in_executor)
```python
import asyncio

async def run_blocking_code():
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, blocking_function, arg1, arg2)
    return result
```

### ✅ NEW (anyio.to_thread)
```python
import anyio

async def run_blocking_code():
    result = await anyio.to_thread.run_sync(blocking_function, arg1, arg2)
    return result
```

**Benefits:**
- ✅ No need to get event loop
- ✅ Simpler API
- ✅ Works across async backends

---

## Pattern 5: Queues / Channels

### ❌ OLD (asyncio.Queue)
```python
import asyncio

async def producer_consumer():
    queue = asyncio.Queue(maxsize=100)
    
    producer_task = asyncio.create_task(producer(queue))
    consumer_task = asyncio.create_task(consumer(queue))
    
    await asyncio.gather(producer_task, consumer_task)

async def producer(queue):
    for i in range(10):
        await queue.put(i)

async def consumer(queue):
    while True:
        item = await queue.get()
        if item is None:
            break
        print(item)
```

### ✅ NEW (anyio memory streams)
```python
import anyio

async def producer_consumer():
    send_stream, receive_stream = anyio.create_memory_object_stream(
        max_buffer_size=100
    )
    
    async with anyio.create_task_group() as tg:
        tg.start_soon(producer, send_stream)
        tg.start_soon(consumer, receive_stream)

async def producer(send_stream):
    async with send_stream:  # Auto-closes on exit
        for i in range(10):
            await send_stream.send(i)
    # Stream closes, consumer will receive end-of-stream

async def consumer(receive_stream):
    async with receive_stream:  # Auto-closes on exit
        async for item in receive_stream:  # Cleaner iteration!
            print(item)
```

**Benefits:**
- ✅ Streams have clear ownership semantics
- ✅ Context managers for automatic cleanup
- ✅ Async iteration support
- ✅ Back-pressure built in

---

## Pattern 6: File I/O

### ❌ OLD (aiofiles or manual)
```python
import aiofiles

async def read_file():
    async with aiofiles.open('file.txt', 'r') as f:
        content = await f.read()
    return content
```

### ✅ NEW (anyio.Path)
```python
import anyio

async def read_file():
    path = anyio.Path('file.txt')
    content = await path.read_text()
    return content

async def write_file():
    path = anyio.Path('output.txt')
    await path.write_text("Hello, world!")
```

**Benefits:**
- ✅ Built-in, no extra dependency
- ✅ pathlib-style API
- ✅ Async file operations

---

## Pattern 7: Running Sync Code in Async Context

### ❌ OLD (asyncio)
```python
import asyncio

# Option 1: run_until_complete (NOT in async context)
def main():
    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(async_function())

# Option 2: asyncio.run (Python 3.7+)
def main():
    result = asyncio.run(async_function())
```

### ✅ NEW (anyio.run)
```python
import anyio

def main():
    result = anyio.run(async_function)  # Note: no parentheses!
    return result

# Or with arguments
def main():
    result = anyio.run(async_function, arg1, arg2)
    return result
```

**Benefits:**
- ✅ Simpler API
- ✅ Works with any async backend
- ✅ Better resource cleanup

---

## Pattern 8: Creating Background Tasks

### ❌ OLD (asyncio.create_task)
```python
import asyncio

async def main():
    # Create background task
    task = asyncio.create_task(background_operation())
    
    # Do other work
    await do_something_else()
    
    # Wait for background task
    await task
```

### ✅ NEW (task groups with start_soon)
```python
import anyio

async def main():
    async with anyio.create_task_group() as tg:
        # Start background task
        tg.start_soon(background_operation)
        
        # Do other work in the same group
        tg.start_soon(do_something_else)
        
        # Both tasks will complete before exiting context
```

**Benefits:**
- ✅ Structured - tasks can't outlive their scope
- ✅ Automatic cleanup
- ✅ Easier error handling

---

## Common Pitfalls & Solutions

### Pitfall 1: Mixing asyncio and anyio
```python
# ❌ BAD - Don't mix!
import asyncio
import anyio

async def broken():
    await asyncio.sleep(1)  # asyncio
    await anyio.sleep(1)    # anyio
    # May cause event loop conflicts!
```

**Solution:** Use anyio exclusively within a module.

---

### Pitfall 2: Not using task groups
```python
# ❌ BAD - Tasks may leak
import anyio

async def broken():
    tg = anyio.create_task_group()
    tg.start_soon(task1)
    tg.start_soon(task2)
    # Forgot to await or use context manager!
```

**Solution:** Always use context manager:
```python
# ✅ GOOD
async def fixed():
    async with anyio.create_task_group() as tg:
        tg.start_soon(task1)
        tg.start_soon(task2)
    # Tasks guaranteed to complete
```

---

### Pitfall 3: Getting event loop directly
```python
# ❌ BAD - Don't access event loop
import asyncio

async def broken():
    loop = asyncio.get_event_loop()
    # ...
```

**Solution:** Let anyio manage the event loop. You rarely need to access it.

---

## Testing with AnyIO

### pytest Configuration

```ini
# pytest.ini
[pytest]
asyncio_mode = auto
anyio_backend = asyncio  # or "trio" for trio backend

markers =
    anyio: mark test as requiring anyio
```

### Test Example

```python
import pytest
import anyio

# Option 1: Use @pytest.mark.anyio
@pytest.mark.anyio
async def test_async_function():
    result = await my_async_function()
    assert result == expected

# Option 2: Use anyio fixture
async def test_with_fixture(anyio_backend):
    # anyio_backend is 'asyncio' or 'trio'
    result = await my_async_function()
    assert result == expected
```

---

## Migration Checklist

Use this checklist when migrating a file:

- [ ] Replace `import asyncio` with `import anyio`
- [ ] Replace `asyncio.sleep()` with `anyio.sleep()`
- [ ] Replace `asyncio.gather()` with task groups
- [ ] Replace `asyncio.wait_for()` with `anyio.fail_after()`
- [ ] Replace `asyncio.create_task()` with task groups + `start_soon()`
- [ ] Replace `loop.run_in_executor()` with `anyio.to_thread.run_sync()`
- [ ] Replace `asyncio.Queue` with memory streams
- [ ] Replace `asyncio.Lock/Event/Semaphore` with anyio equivalents
- [ ] Update tests to use `@pytest.mark.anyio`
- [ ] Run tests to verify nothing broke
- [ ] Update docstrings if they mention asyncio

---

## Resources

- **AnyIO Documentation:** https://anyio.readthedocs.io/
- **Migration Guide:** `/docs/ASYNCIO_TO_ANYIO_MIGRATION.md` (full version)
- **Task Group Tutorial:** https://anyio.readthedocs.io/en/stable/tasks.html
- **Structured Concurrency:** https://vorpus.org/blog/notes-on-structured-concurrency/

---

## Getting Help

If you encounter issues during migration:

1. Check this quick reference
2. Read the full migration guide: `ASYNCIO_TO_ANYIO_MIGRATION.md`
3. Search anyio documentation
4. Ask in team chat with specific code example
5. Create a GitHub issue if you find a migration blocker

---

## Example: Complete File Migration

### BEFORE (asyncio)
```python
"""Example processor using asyncio."""
import asyncio
import logging
from typing import List

logger = logging.getLogger(__name__)

class OldProcessor:
    def __init__(self, max_concurrent: int = 10):
        self.semaphore = asyncio.Semaphore(max_concurrent)
    
    async def process_batch(self, items: List[str]) -> List[str]:
        """Process items concurrently."""
        tasks = [self._process_item(item) for item in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if not isinstance(r, Exception)]
    
    async def _process_item(self, item: str) -> str:
        """Process single item with rate limiting."""
        async with self.semaphore:
            try:
                result = await asyncio.wait_for(
                    self._do_work(item),
                    timeout=30.0
                )
                return result
            except asyncio.TimeoutError:
                logger.error(f"Timeout processing {item}")
                raise
    
    async def _do_work(self, item: str) -> str:
        """Simulate work."""
        await asyncio.sleep(1)
        return f"processed: {item}"

# Usage
def main():
    processor = OldProcessor()
    items = ['a', 'b', 'c']
    results = asyncio.run(processor.process_batch(items))
    print(results)
```

### AFTER (anyio)
```python
"""Example processor using anyio."""
import anyio
import logging
from typing import List

logger = logging.getLogger(__name__)

class NewProcessor:
    def __init__(self, max_concurrent: int = 10):
        self.limiter = anyio.CapacityLimiter(max_concurrent)
    
    async def process_batch(self, items: List[str]) -> List[str]:
        """Process items concurrently."""
        results = []
        
        async with anyio.create_task_group() as tg:
            for item in items:
                tg.start_soon(self._process_and_collect, item, results)
        
        return results
    
    async def _process_and_collect(self, item: str, results: List[str]):
        """Process item and collect result."""
        try:
            result = await self._process_item(item)
            results.append(result)
        except Exception as e:
            logger.error(f"Error processing {item}: {e}")
    
    async def _process_item(self, item: str) -> str:
        """Process single item with rate limiting."""
        async with self.limiter:
            try:
                with anyio.fail_after(30):
                    result = await self._do_work(item)
                    return result
            except TimeoutError:
                logger.error(f"Timeout processing {item}")
                raise
    
    async def _do_work(self, item: str) -> str:
        """Simulate work."""
        await anyio.sleep(1)
        return f"processed: {item}"

# Usage
def main():
    processor = NewProcessor()
    items = ['a', 'b', 'c']
    results = anyio.run(processor.process_batch, items)
    print(results)
```

**Key Changes:**
1. ✅ `import asyncio` → `import anyio`
2. ✅ `asyncio.Semaphore` → `anyio.CapacityLimiter`
3. ✅ `asyncio.gather` → task group with `start_soon`
4. ✅ `asyncio.wait_for` → `anyio.fail_after` context manager
5. ✅ `asyncio.TimeoutError` → standard `TimeoutError`
6. ✅ `asyncio.sleep` → `anyio.sleep`
7. ✅ `asyncio.run` → `anyio.run`

---

**Last Updated:** 2026-02-16  
**Version:** 1.0  
**Maintainer:** Development Team
