
from .citation_validator import CitationValidator
from ._load_citations_for_place import load_citations_for_place
from ._load_documents_for_place import load_documents_for_place
from ._check_code import check_code
from ._check_dates import check_dates
from ._check_format import check_format
from ._check_geography import check_geography
from ._check_section import check_section
from ._save_validation_errors import save_validation_errors

from ipfs_datasets_py.mcp_server.tools.lizardperson_argparse_programs.municipal_bluebook_citation_validator.dependencies import dependencies

def make_citation_validator():
    
    resources = {
        "load_citations_for_place": load_citations_for_place,
        "load_documents_for_place": load_documents_for_place,
        "check_code": check_code,
        "check_dates": check_dates,
        "check_format": check_format,
        "check_geography": check_geography,
        "check_section": check_section, # TODO Make check_section function
        "save_validation_errors": save_validation_errors,
        "duckdb": dependencies.duckdb,
        "logger": dependencies.tqdm
    }

    return CitationValidator(resources=resources, configs=None)