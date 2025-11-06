
from ipfs_datasets_py.mcp_server.tools.lizardperson_argparse_programs.municipal_bluebook_citation_validator.types_ import Container, ProgressBar

def get_pbar(container: Container, desc: str = "Processing...", unit: str = "item") -> ProgressBar:
    from ipfs_datasets_py.mcp_server.tools.lizardperson_argparse_programs.municipal_bluebook_citation_validator.dependencies import dependencies
    return dependencies.tqdm.tqdm(total=len(container), desc=desc, unit=unit)
