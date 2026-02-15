"""
Third-party dependency modules for format handlers.

This package contains processor modules for various file formats and libraries.
"""
from ._bs4_processor import *
from ._calibre_processor import *
from ._cv2_processor import *
from ._ffmpeg_processor import *
from ._icalendar_processor import *
from ._lxml_processor import *
from ._openai_processor import *
from ._openpyxl_processor import *
from ._pandas_processor import *
from ._pil_processor import *
from ._pymediainfo_processor import *
from ._pypdf2_processor import *
from ._pytesseract_processor import *
from ._skeleton_vllm_processor import *

__all__ = [
    '_bs4_processor',
    'calibre_processor',
    'cv2_processor',
    'factory',
    'ffmpeg_processor',
    'generic_html_processor',
    'generic_svg_processor',
    'icalendar_processor',
    'lxml_processor',
    'openai_processor',
    'openpyxl_processor',
    'pandas_processor',
    'pil_processor',
    'pymediainfo_processor',
    'pypdf2_processor',
    'pytesseract_processor',
    'skeleton_vllm_processor',
    'skeleton_xml_processor',
]