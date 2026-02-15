
from ._generic_calendar_processor import *
from ._generic_csv_processor import *
from ._generic_html_processor import *
from ._generic_text_processor import *
from ._generic_xml_processor import *
from ._generic_json_processor import *
from ._generic_markdown_processor import *
from ._generic_svg_processor import *


from .fallback_module_protocol import apply_fallback_module_protocol_to_files_in_this_dir
apply_fallback_module_protocol_to_files_in_this_dir()

__all__ = []