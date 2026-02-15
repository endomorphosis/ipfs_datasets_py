import pytest


from logger.logger import Logger #, LogEntry, LogFile


@pytest.fixture
def test_logger():
    return Logger("test_logger")

# 1. Test message logging

def test_message_logging(test_logger):
    test_logger.info("Test info message")

# 2. Test error logging

# 3. Test log file generation

