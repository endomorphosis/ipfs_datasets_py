from ._setup_database_and_files import SetupDatabaseAndFiles
from ._setup_reference_db import setup_reference_database
from ._setup_error_db import setup_error_database
from ._setup_error_report_db import setup_error_report_database
from configs import configs

def make_setup_database_and_files():
    resources = {
        "setup_reference_db": setup_reference_database,
        "setup_error_db": setup_error_database,
        "setup_error_report_db": setup_error_report_database,
    }
    return SetupDatabaseAndFiles(resources=resources, configs=configs)
