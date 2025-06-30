"""
Lazy loading of dependencies to optimize performance and reduce initial load time.

Tools can access these dependencies via the `dependencies` object.
"""
from importlib import import_module as _import_module # NOTE We call this outside of the class to avoid circular imports.

class _PythonBuiltins:

    def __init__(self):
        self._cache = {
            "abc": None,
            "argparse": None,
            "array": None,
            "ast": None,
            "atexit": None,
            "base64": None,
            "bisect": None,
            "calendar": None,
            "codecs": None,
            "collections": None,
            "configparser": None,
            "contextlib": None,
            "copy": None,
            "csv": None,
            "ctypes": None,
            "datetime": None,
            "decimal": None,
            "enum": None,
            "fnmatch": None,
            "fractions": None,
            "functools": None,
            "gc": None,
            "getpass": None,
            "glob": None,
            "gzip": None,
            "hashlib": None,
            "heapq": None,
            "html": None,
            "http": None,
            "inspect": None,
            "io": None,
            "itertools": None,
            "json": None,
            "keyword": None,
            "logging": None,
            "math": None,
            "mmap": None,
            "multiprocessing": None,
            "mutex": None,
            "operator": None,
            "os": None,
            "pathlib": None,
            "pickle": None,
            "platform": None,
            "pprint": None,
            "queue": None,
            "random": None,
            "re": None,
            "readline": None,
            "reprlib": None,
            "rlcompleter": None,
            "sched": None,
            "secrets": None,
            "shutil": None,
            "socket": None,
            "sqlite3": None,
            "statistics": None,
            "string": None,
            "struct": None,
            "subprocess": None,
            "sys": None,
            "tarfile": None,
            "tempfile": None,
            "textwrap": None,
            "threading": None,
            "time": None,
            "traceback": None,
            "types": None,
            "unicodedata": None,
            "urllib": None,
            "uuid": None,
            "warnings": None,
            "weakref": None,
            "xml": None,
            "zipfile": None,
        }

    def _load_module(self, module_name: str):
        if self._cache[module_name] is None:
            try:
                self._cache[module_name] = _import_module(module_name)
            except Exception as e:
                raise ImportError(f"Module '{module_name}' could not be imported: {e}.") from e
        return self._cache[module_name]

    def __str__(self):
        return "_PythonBuiltins"

    def startswith(self, prefix: str) -> bool:
        import traceback
        print(f"startswith called with prefix: {prefix}")
        print("Call stack:")
        traceback.print_stack()
        return str(self).startswith(prefix)

    @property
    def abc(self):
        return self._load_module('abc')

    @property
    def argparse(self):
        return self._load_module('argparse')

    @property
    def array(self):
        return self._load_module('array')

    @property
    def ast(self):
        return self._load_module('ast')

    @property
    def atexit(self):
        return self._load_module('atexit')

    @property
    def base64(self):
        return self._load_module('base64')

    @property
    def bisect(self):
        return self._load_module('bisect')

    @property
    def calendar(self):
        return self._load_module('calendar')

    @property
    def codecs(self):
        return self._load_module('codecs')

    @property
    def collections(self):
        return self._load_module('collections')

    @property
    def configparser(self):
        return self._load_module('configparser')

    @property
    def contextlib(self):
        return self._load_module('contextlib')

    @property
    def copy(self):
        return self._load_module('copy')

    @property
    def csv(self):
        return self._load_module('csv')

    @property
    def ctypes(self):
        return self._load_module('ctypes')

    @property
    def datetime(self):
        return self._load_module('datetime')

    @property
    def decimal(self):
        return self._load_module('decimal')

    @property
    def enum(self):
        return self._load_module('enum')

    @property
    def fnmatch(self):
        return self._load_module('fnmatch')

    @property
    def fractions(self):
        return self._load_module('fractions')

    @property
    def functools(self):
        return self._load_module('functools')

    @property
    def gc(self):
        return self._load_module('gc')

    @property
    def getpass(self):
        return self._load_module('getpass')

    @property
    def glob(self):
        return self._load_module('glob')

    @property
    def gzip(self):
        return self._load_module('gzip')

    @property
    def hashlib(self):
        return self._load_module('hashlib')

    @property
    def heapq(self):
        return self._load_module('heapq')

    @property
    def html(self):
        return self._load_module('html')

    @property
    def http(self):
        return self._load_module('http')

    @property
    def inspect(self):
        return self._load_module('inspect')

    @property
    def io(self):
        return self._load_module('io')

    @property
    def itertools(self):
        return self._load_module('itertools')

    @property
    def json(self):
        return self._load_module('json')

    @property
    def keyword(self):
        return self._load_module('keyword')

    @property
    def logging(self):
        return self._load_module('logging')

    @property
    def math(self):
        return self._load_module('math')

    @property
    def mmap(self):
        return self._load_module('mmap')

    @property
    def multiprocessing(self):
        return self._load_module('multiprocessing')

    @property
    def mutex(self):
        return self._load_module('mutex')

    @property
    def operator(self):
        return self._load_module('operator')

    @property
    def os(self):
        return self._load_module('os')

    @property
    def pathlib(self):
        return self._load_module('pathlib')

    @property
    def pickle(self):
        return self._load_module('pickle')

    @property
    def platform(self):
        return self._load_module('platform')

    @property
    def pprint(self):
        return self._load_module('pprint')

    @property
    def queue(self):
        return self._load_module('queue')

    @property
    def random(self):
        return self._load_module('random')

    @property
    def re(self):
        return self._load_module('re')

    @property
    def readline(self):
        return self._load_module('readline')

    @property
    def reprlib(self):
        return self._load_module('reprlib')

    @property
    def rlcompleter(self):
        return self._load_module('rlcompleter')

    @property
    def sched(self):
        return self._load_module('sched')

    @property
    def secrets(self):
        return self._load_module('secrets')

    @property
    def shutil(self):
        return self._load_module('shutil')

    @property
    def socket(self):
        return self._load_module('socket')

    @property
    def sqlite3(self):
        return self._load_module('sqlite3')

    @property
    def statistics(self):
        return self._load_module('statistics')

    @property
    def string(self):
        return self._load_module('string')

    @property
    def struct(self):
        return self._load_module('struct')

    @property
    def subprocess(self):
        return self._load_module('subprocess')

    @property
    def sys(self):
        return self._load_module('sys')

    @property
    def tarfile(self):
        return self._load_module('tarfile')

    @property
    def tempfile(self):
        return self._load_module('tempfile')

    @property
    def textwrap(self):
        return self._load_module('textwrap')

    @property
    def threading(self):
        return self._load_module('threading')

    @property
    def time(self):
        return self._load_module('time')

    @property
    def traceback(self):
        return self._load_module('traceback')

    @property
    def types(self):
        return self._load_module('types')

    @property
    def unicodedata(self):
        return self._load_module('unicodedata')

    @property
    def urllib(self):
        return self._load_module('urllib')

    @property
    def uuid(self):
        return self._load_module('uuid')

    @property
    def warnings(self):
        return self._load_module('warnings')

    @property
    def weakref(self):
        return self._load_module('weakref')

    @property
    def xml(self):
        return self._load_module('xml')

    @property
    def zipfile(self):
        return self._load_module('zipfile')

python_builtins = _PythonBuiltins()
