import sys
import traceback


from .logger import Logger
logger = Logger("UNCAUGHT_EXCEPTION")


def handle_uncaught_exception(exc_type, exc_value, exc_traceback):
    """
    Handle uncaught exceptions in the application.

    This function is designed to be used as a custom exception handler for sys.excepthook.
    It logs critical errors with detailed information about the exception, excluding
    KeyboardInterrupt exceptions.

    Args:
        exc_type (Type[BaseException]): The type of the exception.
        exc_value (BaseException): The exception instance.
        exc_traceback (TracebackType): A traceback object encapsulating the call stack at the point where the exception occurred.

    Returns:
        None

    NOTE:
        THIS FILE NEEDS TO BE IMPORTED INTO ANOTHER MODULE (.e.g main.py, __init__.py) FOR THIS TO WORK!
        See: https://stackoverflow.com/questions/6234405/logging-uncaught-exceptions-in-python
        See: https://stackoverflow.com/questions/48642111/can-i-make-python-output-exceptions-in-one-line-via-logging
        See: https://stackoverflow.com/questions/48170682/can-structured-logging-be-done-with-pythons-standard-library/48202500#48202500
    """
    exc_info = (exc_type, exc_value, exc_traceback)

    # Ignore keyboard interrupts.
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(*exc_info)
    else:
        exc_traceback = str("\n".join(traceback.format_tb(exc_traceback)))

        write_val = f"""
        exc_type: {str(exc_type)}
        exc_value: {str(exc_value)}
        exc_traceback: {exc_traceback}
        """
        logger.critical(f"!!! Uncaught Exception !!!\n{write_val}", f=True, t=5)
    return


sys.excepthook = handle_uncaught_exception
