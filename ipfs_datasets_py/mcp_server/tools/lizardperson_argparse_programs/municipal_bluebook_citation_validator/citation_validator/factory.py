
from ._citation_validator import CitationValidator
from ._load_citations_for_place import load_citations_for_place
from ._load_documents_for_place import load_documents_for_place


def make_citation_validator():
    
    resources = {
        "load_citations_for_place": load_citations_for_place,
        "load_documents_for_place": load_documents_for_place,
    }

    return CitationValidator(resources=resources, configs=None)