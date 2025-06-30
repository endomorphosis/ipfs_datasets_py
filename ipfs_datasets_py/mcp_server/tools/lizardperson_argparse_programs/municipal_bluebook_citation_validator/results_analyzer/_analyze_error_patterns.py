


# Step 4: Analysis and Reporting Functions
def analyze_error_patterns(error_db, logger) -> dict[str, int]:  # -> ErrorSummary
    """Count up all the errors we found by type and severity."""
    try:
        # Initialize error summary dictionary
        error_summary = {
            'total_errors': 0,
            'geography_errors': 0,
            'type_errors': 0,
            'section_errors': 0,
            'date_errors': 0,
            'format_errors': 0,
            'critical_errors': 0,
            'minor_errors': 0
        }
        
        # Query to get all error records
        result = error_db.sql("SELECT * FROM errors").fetchall()
        
        if not result:
            logger.info("No errors found in database")
            return error_summary
        
        # Count each type of error
        for row in result:
            error_summary['total_errors'] += 1
            
            # Count specific error types (columns 2-6 are boolean error flags)
            geography_error, section_error, date_error, format_error = row[2:6]
            
            if geography_error:
                error_summary['geography_errors'] += 1
                error_summary['critical_errors'] += 1
            if section_error:
                error_summary['section_errors'] += 1
                error_summary['minor_errors'] += 1
            if date_error:
                error_summary['date_errors'] += 1
                error_summary['minor_errors'] += 1
            if format_error:
                error_summary['format_errors'] += 1
                error_summary['minor_errors'] += 1
        
        # Log summary for debugging
        logger.info(f"Error analysis complete: {error_summary['total_errors']} total errors found")
        
        return error_summary
        
    except Exception as e:
        logger.error(f"Error analyzing error patterns: {e}")
        return {
            'total_errors': 0,
            'geography_errors': 0,
            'type_errors': 0,
            'section_errors': 0,
            'date_errors': 0,
            'format_errors': 0,
            'critical_errors': 0,
            'minor_errors': 0
        }
