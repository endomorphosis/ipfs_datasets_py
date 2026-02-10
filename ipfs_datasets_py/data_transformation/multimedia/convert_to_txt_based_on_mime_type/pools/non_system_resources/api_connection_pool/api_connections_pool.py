
"""
Implementing pooling of connections to APIs
    This pooling supports both API connections 
    and Models loaded in from the Transformers library.
"""
from __future__ import annotations

import queue
import random
import re
import threading

from types import TracebackType
from typing import TYPE_CHECKING, Any, Dict, NoReturn, Optional, Tuple, Type, Union
from uuid import uuid4

API_CONNECTION_POOL_LOCK = threading.RLock()
CNX_POOL_MAXSIZE = 32
CNX_POOL_MAXNAMESIZE = 64
CNX_POOL_NAMEREGEX = re.compile(r"[^a-zA-Z0-9._:\-*$#]")
ERROR_NO_CEXT = "MySQL Connector/Python C Extension not available"

_CONNECTION_POOLS: Dict[str, ApiConnectionPool] = {}

class Error(Exception):
    pass

class InterfaceError(Exception):
    pass

class PoolError(Exception):
    pass

class NotSupportedError(Exception):
    pass

class ProgrammingError(Exception):
    pass


MYSQL_CNX_CLASS = None


from external_interface.api_manager.api_manager import ApiConnection, ApiManager
from pydantic_models.configs import Configs
from logger.logger import Logger

# TODO: Fix this import statement
# from .constants import CNX_POOL_ARGS, DEFAULT_CONFIGURATION

CNX_POOL_ARGS = None
DEFAULT_CONFIGURATION = None

def _get_pooled_connection(**kwargs: Any) -> PooledApiConnection:
    """
    Return a pooled API connection.
    """
    # If no pool name specified, generate one
    pool_name = (
        kwargs["pool_name"] if "pool_name" in kwargs else generate_pool_name(**kwargs)
    )

    # Setup the pool, ensuring only 1 thread can update at a time
    with API_CONNECTION_POOL_LOCK:
        if pool_name not in _CONNECTION_POOLS:
            _CONNECTION_POOLS[pool_name] = PooledApiConnection(**kwargs)

        elif isinstance(_CONNECTION_POOLS[pool_name], PooledApiConnection):
            # pool_size must be the same
            check_size = _CONNECTION_POOLS[pool_name].pool_size
            if "pool_size" in kwargs and kwargs["pool_size"] != check_size:
                raise PoolError("Size can not be changed for active pools.")

    # Return pooled connection
    try:
        return _CONNECTION_POOLS[pool_name].get_connection()
    except AttributeError:
        raise InterfaceError(
            f"Failed getting connection from pool '{pool_name}'"
        ) from None


def read_option_files(**kwargs):
    return {key: value for key, value in kwargs} 


def connect(
    *args: Any, **kwargs: Any
) -> Union[PooledApiConnection, ApiConnection]:
    """Requests an ApiConnection object.

    In its simplest form, `connect()` will request an API connection object
    from the External Resource Manager (ERM) and return it.

    When any connection pooling arguments are given, for example `pool_name`
    or `pool_size`, a pool is created or a previously one is used to return
    a `PooledApiConnection`.

    Args:
        *args: N/A.
        **kwargs: For a complete list of possible arguments, see [1]. If no arguments
                  are given, it uses the already configured or default values.

    Returns:
        A `ApiConnectionAbstract` subclass instance (such as `ApiConnection` or
        `CApiConnection`) or a `PooledApiConnection` instance.

    Examples:
        A connection with the MySQL server can be established using either the
        `mysql.connector.connect()` method or a `ApiConnectionAbstract` subclass:
        ```
        >>> from mysql.connector import ApiConnection, HAVE_CEXT
        >>>
        >>> cnx1 = mysql.connector.connect(user='joe', database='test')
        >>> cnx2 = ApiConnection(user='joe', database='test')
        ```

    References:
        [1]: https://dev.mysql.com/doc/connector-python/en/connector-python-connectargs.html
    """
    if "":
        pass

    if "host" not in kwargs:
        kwargs["host"] = DEFAULT_CONFIGURATION["host"]

    # Option files
    if "read_default_file" in kwargs:
        kwargs["option_files"] = kwargs["read_default_file"]
        kwargs.pop("read_default_file")

    if "option_files" in kwargs:
        new_config = read_option_files(**kwargs)
        return connect(**new_config)

    # Pooled connections
    try:
        if any(key in kwargs for key in CNX_POOL_ARGS):
            return _get_pooled_connection(**kwargs)
    except NameError:
        # No pooling
        pass

    return ApiConnection(*args, **kwargs)



def generate_pool_name(**kwargs: Any) -> str:
    """Generate a pool name

    This function takes keyword arguments, usually the connection
    arguments for ApiConnection, and tries to generate a name for
    a pool.

    Raises PoolError when no name can be generated.

    Returns a string.
    """
    parts = []
    for key in ("host", "port", "user", "database"):
        try:
            parts.append(str(kwargs[key]))
        except KeyError:
            pass

    if not parts:
        raise PoolError("Failed generating pool name; specify pool_name")

    return "_".join(parts)




class ApiConnectionPool:
    """Class defining a pool of ApiConnection objects."""

    def __init__(
        self,
        pool_size: int = 5,
        pool_name: Optional[str] = None,
        pool_reset_session: bool = True,
        **kwargs: Any,
    ) -> None:
        """Constructor.

        Initialize an ApiConnection pool with a maximum number of
        connections set to `pool_size`. The rest of the keywords
        arguments, kwargs, are configuration arguments for ApiConnection
        instances.

        Args:
            pool_name: The pool name. If this argument is not given, Connector/Python
                       automatically generates the name, composed from whichever of
                       the host, port, user, and database connection arguments are
                       given in kwargs, in that order.
            pool_size:  The pool size. If this argument is not given, the default is 5.
            pool_reset_session: Whether to reset session variables when the connection
                                is returned to the pool.
            **kwargs: Optional additional connection arguments, as described in [1].

        Examples:
            ```
            >>> from pools.non_system_resources.api_connection_pool.api_connection_pool import ApiConnectionPool
            >>> import mysql.connector
            >>> dbconfig = {
            >>>     "database": "test",
            >>>     "user":     "joe",
            >>> }
            >>> cnxpool = ApiConnectionPool(
            >>>     pool_name = "mypool",
            >>>     pool_size = 3,
            >>>     **dbconfig)
            ```

        References:
            [1]: https://dev.mysql.com/doc/connector-python/en/connector-python-connectargs.html
        """
        self._pool_size: Optional[int] = None
        self._pool_name: Optional[str] = None
        self._reset_session = pool_reset_session
        self._set_pool_size(pool_size)
        self._set_pool_name(pool_name or generate_pool_name(**kwargs))
        self._cnx_config: Dict[str, Any] = {}
        self._cnx_queue: queue.Queue[ApiConnection] = queue.Queue(
            self._pool_size
        )
        self._config_version = uuid4()

    @property
    def pool_name(self) -> str:
        """Returns the name of the connection pool."""
        return self._pool_name

    @property
    def pool_size(self) -> int:
        """Returns number of connections managed by the pool."""
        return self._pool_size

    @property
    def reset_session(self) -> bool:
        """Returns whether to reset session."""
        return self._reset_session

    def set_config(self, **kwargs: Any) -> None:
        """Set the connection configuration for `ApiConnectionAbstract` subclass instances.

        This method sets the configuration used for creating `ApiConnectionAbstract`
        subclass instances such as `ApiConnection`. See [1] for valid
        connection arguments.

        Args:
            **kwargs: Connection arguments - for a complete list of possible
                      arguments, see [1].

        Raises:
            PoolError: When a connection argument is not valid, missing
                       or not supported by `ApiConnectionAbstract`.

        References:
            [1]: https://dev.mysql.com/doc/connector-python/en/connector-python-connectargs.html
        """
        if not kwargs:
            return

        with API_CONNECTION_POOL_LOCK:
            try:
                test_cnx = connect()
                test_cnx.config(**kwargs)
                self._cnx_config = kwargs
                self._config_version = uuid4()
            except AttributeError as err:
                raise PoolError(f"Connection configuration not valid: {err}") from err


    def _set_pool_size(self, pool_size: int) -> None:
        """Set the size of the pool

        This method sets the size of the pool but it will not resize the pool.

        Raises an AttributeError when the pool_size is not valid. Invalid size
        is 0, negative or higher than pooling.CNX_POOL_MAXSIZE.
        """
        if pool_size <= 0 or pool_size > CNX_POOL_MAXSIZE:
            raise AttributeError(
                "Pool size should be higher than 0 and lower or equal to "
                f"{CNX_POOL_MAXSIZE}"
            )
        self._pool_size = pool_size


    def _set_pool_name(self, pool_name: str) -> None:
        r"""Set the name of the pool.

        This method checks the validity and sets the name of the pool.

        Raises an AttributeError when pool_name contains illegal characters
        ([^a-zA-Z0-9._\-*$#]) or is longer than pooling.CNX_POOL_MAXNAMESIZE.
        """
        if CNX_POOL_NAMEREGEX.search(pool_name):
            raise AttributeError(f"Pool name '{pool_name}' contains illegal characters")

        if len(pool_name) > CNX_POOL_MAXNAMESIZE:
            raise AttributeError(f"Pool name '{pool_name}' is too long")

        self._pool_name = pool_name


    def _queue_connection(self, cnx: ApiConnection) -> None:
        """Put connection back in the queue

        This method puts a connection back in the queue. It will not
        acquire a lock as the methods using _queue_connection() will have it
        set.

        Raises `PoolError` on errors.
        """
        if not isinstance(cnx, ApiConnection):
            raise PoolError(
                "Connection instance not an ApiConnection instance"
            )

        try:
            self._cnx_queue.put(cnx, block=False)
        except queue.Full as err:
            raise PoolError("Failed adding connection; queue is full") from err


    def add_connection(self, cnx: Optional[ApiConnection] = None) -> None:
        """Adds a connection to the pool.

        This method requests a `ApiConnection` from the ERM using the configuration
        passed when initializing the `ApiConnectionPool` instance or using
        the `set_config()` method.
        If cnx is a `ApiConnection` instance, it will be added to the
        queue.

        Args:
            cnx: The `ApiConnection`  object to be added to the pool. 
                If this argument is None, the pool requests a new connection 
                from the External Resource Manager.

        Raises:
            PoolError: When no configuration is set, when no more
                       connection can be added (maximum reached) or when the connection
                       can not be instantiated.
        """
        with API_CONNECTION_POOL_LOCK:
            if not self._cnx_config:
                raise PoolError("Connection configuration not available")

            if self._cnx_queue.full():
                raise PoolError("Failed adding connection; queue is full")

            if not cnx:
                cnx = connect(**self._cnx_config)  # type: ignore[assignment]
                try:
                    if (
                        self._reset_session
                        and self._cnx_config["compress"]
                        and cnx.get_server_version() < (5, 7, 3)
                    ):
                        raise NotSupportedError(
                            "Pool reset session is not supported with "
                            "compression for MySQL server version 5.7.2 "
                            "or earlier"
                        )
                except KeyError:
                    pass

                cnx.pool_config_version = self._config_version
            else:
                if not isinstance(cnx, MYSQL_CNX_CLASS):
                    raise PoolError(
                        "Connection instance not subclass of ApiConnectionAbstract"
                    )

            self._queue_connection(cnx)


    def get_connection(self) -> PooledApiConnection:
        """Gets a connection from the pool.

        This method returns an PooledApiConnection instance which
        has a reference to the pool that created it, and the next available
        API connection.

        When the API connection is not connect, a reconnect is attempted.

        Returns:
            A `PooledApiConnection` instance.

        Raises:
            PoolError: On errors.
        """
        with API_CONNECTION_POOL_LOCK:
            try:
                cnx: ApiConnection = self._cnx_queue.get(block=False)
            except queue.Empty as err:
                raise PoolError("Failed getting connection; pool exhausted") from err

            if (
                not cnx.is_connected()
                or self._config_version != cnx.pool_config_version
            ):
                cnx.config(**self._cnx_config)
                try:
                    cnx.reconnect()
                except InterfaceError:
                    # Failed to reconnect, give connection back to pool
                    self._queue_connection(cnx)
                    raise
                cnx.pool_config_version = self._config_version

            return PooledApiConnection(self, cnx)


    def _remove_connections(self) -> int:
        """Close all connections

        This method closes all connections. It returns the number
        of connections it closed.

        Used mostly for tests.

        Returns int.
        """
        with API_CONNECTION_POOL_LOCK:
            cnt = 0
            cnxq = self._cnx_queue
            while cnxq.qsize():
                try:
                    cnx = cnxq.get(block=False)
                    cnx.disconnect()
                    cnt += 1
                except queue.Empty:
                    return cnt
                except PoolError:
                    raise
                except Error:
                    # Any other error when closing means connection is closed
                    pass

            return cnt



class PooledApiConnection:
    """
    NOTE: This is lifted directly from the `PooledApiConnection` class in
    the `mysql.connector` package. Except for variable renames and docstrings, 
    it is unchanged unless otherwise noted.

    Class holding an API Connection in a pool

    PooledApiConnection is used by ApiConnectionPool to return an
    instance holding an API connection. It works like an ApiConnection
    except for methods like close() and config().

    The close()-method will add the connection back to the pool rather
    than destroying the ApiConnection object.

    Configuring the connection has to be done through the ApiConnectionPool
    method set_config(). Using config() on pooled connection will raise a
    PoolError.

    Attributes:
        pool_name (str): Returns the name of the connection pool to which the
                         connection belongs.
    """

    def __init__(self, pool: ApiConnectionPool, cnx: ApiConnection):
        """Constructor.

        Args:
            pool: A `ApiConnectionPool` instance.
            cnx: A `ApiConnection` subclass instance.
        """
        if not isinstance(pool, ApiConnectionPool):
            raise AttributeError("pool should be a ApiConnectionPool")
        if not isinstance(cnx, ApiConnection):
            raise AttributeError("cnx should be a ApiConnectionPool")

        self._cnx_pool: ApiConnectionPool = pool
        self._cnx: ApiConnection = cnx

    def __enter__(self) -> 'PooledApiConnection':
        return self

    def __exit__(
        self, exc_type: Type[BaseException], exc_value: BaseException, traceback: TracebackType,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Do not close, but adds connection back to pool.

        For a pooled connection, close() does not actually close it but returns it
            to the pool and makes it available for subsequent connection requests. 
            If the pool configuration parameters are changed, a returned connection is closed
            and reopened with the new configuration before being returned from the pool
            again in response to a connection request.
        """
        try:
            cnx = self._cnx
            if self._cnx_pool.reset_session:
                cnx.reset_session()
        finally:
            self._cnx_pool.add_connection(cnx)
            self._cnx = None

    def __getattr__(self, attr: Any) -> Any:
        """Calls attributes of the ApiConnection instance"""
        return getattr(self._cnx, attr)

    @staticmethod
    def config(**kwargs: Any) -> NoReturn:
        """Configuration is done through the pool.

        For pooled connections, the `config()` method raises a `PoolError`
        exception. Configuration for pooled connections should be done
        using the pool object.
        """
        raise PoolError(
            "Configuration for pooled connections should be done through the pool itself"
        )

    @property
    def pool_name(self) -> str:
        """Returns the name of the connection pool to which the connection belongs."""
        return self._cnx_pool.pool_name




