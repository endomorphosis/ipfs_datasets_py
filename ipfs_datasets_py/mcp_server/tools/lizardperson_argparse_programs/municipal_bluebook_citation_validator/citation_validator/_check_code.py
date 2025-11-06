

from ipfs_datasets_py.mcp_server.tools.lizardperson_argparse_programs.municipal_bluebook_citation_validator.types_ import DatabaseConnection

def check_code(citation: dict, reference_db: DatabaseConnection, logger) -> dict:  # -> ValidationResult
    """Check: Should this be 'County Code' or 'City Code'?"""
    try:
        gnis = citation.get('gnis')
        cited_code_type = citation.get('code_type')
        
        if not gnis or not cited_code_type:
            return {
                'valid': False,
                'error_type': 'type_error',
                'message': 'Missing GNIS or code_type information in citation'
            }

        # Query the reference database to get the place type
        query = f"SELECT feature_class FROM locations WHERE gnis = {gnis}"
        result = reference_db.sql(query).fetchone()

        if not result:
            return {
                'valid': False,
                'error_type': 'type_error',
                'message': f'GNIS {gnis} not found in reference database'
            }
        
        feature_class = result[0]
        
        # Determine expected code type based on feature class
        # Cities/towns should use "City Code", counties should use "County Code"
        if feature_class.lower() in ['populated place', 'city', 'town', 'village']:
            expected_code_type = 'City Code'
        elif feature_class.lower() in ['civil', 'county']:
            expected_code_type = 'County Code'
        else:
            return {
                'valid': False,
                'error_type': 'type_error',
                'message': f'Unknown feature class: {feature_class}'
            }
        
        # Compare cited code type with expected type
        if cited_code_type.strip() != expected_code_type:
            return {
                'valid': False,
                'error_type': 'type_error',
                'message': f'Code type mismatch: cited as {cited_code_type}, should be {expected_code_type} for {feature_class}'
            }

        return {
            'valid': True,
            'error_type': None,
            'message': 'Code type check passed'
        }

    except Exception as e:
        logger.error(f"Error in code type check: {e}")
        return {
            'valid': False,
            'error_type': 'type_error',
            'message': f'Code type check failed with error: {str(e)}'
        }