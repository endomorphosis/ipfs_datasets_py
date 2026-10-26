#!/usr/bin/env python3
"""pa_exit_guard - safe process exit for scripts that read parquet with pyarrow in /workspace/venv (pandas 3.0.6, numpy 2.5.3, pyarrow 25.0.1, Python 3.13.5).

Problem: after pq.read_table() (which lazily imports pandas), normal interpreter shutdown can abort in a C++ destructor with
'terminate called without an active exception' (SIGABRT, exit 134) although all work has finished. Measured 2026-10-06: it is a shutdown
race - most runs abort even after the Table was freed; `del` + gc.collect() lowers the rate but does not remove it; os._exit() after
flushing removes it. So: release objects (safe part) AND leave through os._exit with the REAL exit code (this module).

Entrypoint (function-style script):
    import pa_exit_guard as EG
    if __name__ == '__main__': EG.run_guarded(main)        # or EG.run_guarded(fn, arg1, ...)
Module-level script (no main()): `pa_exit_guard.install()` near the top, `pa_exit_guard.finish(0)` as the last line.
Build/verify/push functions: close writers, `del` Tables / ParquetFile objects / readers / writers, then `release()` (gc.collect()).

Exit code = what the interpreter would have used:
    return None, sys.exit(), sys.exit(None)        -> 0
    return <int>, sys.exit(<int>)                  -> that int (other return values are ignored -> 0, as Python ignores them)
    sys.exit('message')                            -> message printed to stderr, 1
    uncaught exception                             -> traceback printed to stderr, 1   (KeyboardInterrupt: traceback, 130)
Before os._exit: non-daemon threads are joined and atexit handlers run (as in a normal shutdown), still-open writable file objects are
flushed, logging handlers and the given log files are closed, stdout/stderr are flushed (stdout flush failure on success -> 120, as Python).
Never hard-codes 0.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import atexit, gc, io, logging, os, sys, threading, traceback

__all__ = ['release', 'run_guarded', 'finish', 'install', 'exit_code_of']


def release(*objs):
    """close() every given object that has a close() (pass writers first: ParquetWriter, then ParquetFile/readers/file handles), then gc.collect().
    A failing close() of a writer is a real failure and is NOT swallowed. The caller must still `del` its own names."""
    for o in objs:
        c = getattr(o, 'close', None)
        if callable(c):
            c()
    del objs
    gc.collect()


def exit_code_of(code):
    """SystemExit.code -> process exit status, same rules as CPython (non-int: printed to stderr, status 1)."""
    if code is None:
        return 0
    if isinstance(code, int):
        return int(code) if -2 ** 31 <= code < 2 ** 31 else 1
    try:
        print(code, file=sys.stderr, flush=True)
    except Exception:
        pass
    return 1


def _flush_open_files():
    """flush still-open writable file objects (a normal shutdown would flush them while finalizing; os._exit does not). Returns failures."""
    bad = []
    skip = {id(sys.stdout), id(sys.stderr), id(sys.__stdout__), id(sys.__stderr__)}
    for o in gc.get_objects():
        try:
            if isinstance(o, io.IOBase) and id(o) not in skip and not o.closed and o.writable():
                o.flush()
        except ValueError:
            pass        # closed in the meantime / detached
        except Exception as e:
            bad.append(f'{getattr(o, "name", type(o).__name__)}: {e!r}')
    return bad


def finish(code, logs=()):
    """orderly end: join non-daemon threads, run atexit handlers, flush open files, close logging + the given log files, flush stdio, os._exit(code)."""
    try:
        me = threading.current_thread()
        for t in threading.enumerate():
            if t is not me and not t.daemon and t.is_alive():
                t.join()
    except BaseException:
        traceback.print_exc()
    try:
        atexit._run_exitfuncs()       # exceptions inside are reported by atexit itself; like Python they do not change the code
    except BaseException:
        traceback.print_exc()
    for f in logs or ():
        try:
            f.flush(); f.close()
        except Exception as e:
            print(f'pa_exit_guard: closing log {getattr(f, "name", f)!r} failed: {e!r}', file=sys.stderr)
    try:
        logging.shutdown()
    except Exception:
        traceback.print_exc()
    bad = _flush_open_files()
    if bad:
        print('pa_exit_guard: flush failed for ' + '; '.join(bad[:10]), file=sys.stderr)
        if code == 0:
            code = 1
    try:
        sys.stderr.flush()
    except Exception:
        pass
    try:
        sys.stdout.flush()
    except Exception:
        if code == 0:
            code = 120                # CPython: exit status 120 when flushing stdout fails at shutdown
    for s in (sys.__stdout__, sys.__stderr__):
        try:
            if s is not None:
                s.flush()
        except Exception:
            pass
    os._exit(code)


def run_guarded(main_fn, *args, logs=(), **kwargs):
    """run main_fn(*args, **kwargs), compute the real exit code, then finish(code). Does not return."""
    code = 1
    try:
        r = main_fn(*args, **kwargs)
        code = int(r) if isinstance(r, int) and not isinstance(r, bool) else 0
    except SystemExit as e:
        code = exit_code_of(e.code)
    except KeyboardInterrupt:
        traceback.print_exc(); code = 130
    except BaseException:
        traceback.print_exc(); code = 1
    finish(code, logs)


def _excepthook(tp, val, tb):
    traceback.print_exception(tp, val, tb)
    finish(130 if issubclass(tp, KeyboardInterrupt) else 1)


def install():
    """for module-level scripts: an uncaught exception prints its traceback and exits 1 via finish(); end the script with finish(0)."""
    sys.excepthook = _excepthook
