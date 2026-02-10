# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/lizardperson_argparse_programs/municipal_bluebook_citation_validator/utils/run_in_thread_pool.py'

Files last updated: 1751408933.7364564

Stub file last updated: 2025-07-07 01:10:14

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
