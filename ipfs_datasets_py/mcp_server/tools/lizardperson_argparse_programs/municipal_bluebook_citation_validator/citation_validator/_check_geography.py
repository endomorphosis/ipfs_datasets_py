

from ipfs_datasets_py.mcp_server.tools.lizardperson_argparse_programs.municipal_bluebook_citation_validator.types_ import DatabaseConnection

def check_geography(citation: dict, reference_db: DatabaseConnection) -> str | None:
    """Check: Is Garland really in Arkansas?"""
    try:
        gnis = citation['gnis']
        cited_state = citation['state']
    except KeyError:
        return 'Missing GNIS or state information in citation'

    # Query the reference database to get the actual state for this GNIS
    query = f"SELECT state_name FROM locations WHERE gnis = {gnis}"
    try:
        result = reference_db.sql(query).fetchone()
        if not result:
            return f'GNIS {gnis} not found in reference database'
    except Exception as e:
            return f'GNIS {gnis} not found in reference database'

    actual_state = result[0]

    # Compare cited state with actual state
    if cited_state.lower().strip() != actual_state.lower().strip():
        return f'State mismatch: cited as {cited_state}, actually in {actual_state}'

    return None  # No error found

