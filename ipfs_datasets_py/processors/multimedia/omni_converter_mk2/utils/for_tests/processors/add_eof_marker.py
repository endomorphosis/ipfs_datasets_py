from utils.common.try_except_decorator import try_except
from logger import logger

file_errors = (
    IOError, # Error when opening
    FileNotFoundError,
    IsADirectoryError,
    PermissionError, # Error when reading
    ValueError, # Bad file format
    OSError, # Error when writing
    TypeError,
    Exception,
)

@try_except(raise_=False, exception_type=file_errors, msg="Error in fix_pdf_eof", default_return=False)
def fix_pdf_eof(pdf_path):
    """
    Checks if a PDF has an EOF marker and adds one if missing.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        True if the file was fixed or already had an EOF, False if error
    """
    with open(pdf_path, 'rb') as f:
        content = f.read()

    # Check if EOF marker already exists
    if content.strip().endswith(b'%%EOF'):
        logger.debug("EOF marker already exists")
        return True

    # Add the marker if it doesn't exist
    with open(pdf_path, 'ab') as f:
        f.write(b'\n%%EOF')
    logger.debug("EOF marker added successfully")
    return True


