# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/utils/common/run_in_thread_pool.py'

Files last updated: 1750480072.804435

Stub file last updated: 2025-07-17 05:30:21

## run_in_thread_pool

```python
def run_in_thread_pool(func, inputs, *, max_concurrency: int = 5, use_tqdm: bool = True):
    """
    Calls the function ``func`` on the values ``inputs``.

``func`` should be a function that takes a single input, which is the
individual values in the iterable ``inputs``.

Generates (input, output) tuples as the calls to ``func`` complete.

See https://alexwlchan.net/2019/10/adventures-with-concurrent-futures/ for an explanation
of how this function works.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
