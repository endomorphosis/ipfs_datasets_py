
from datetime import datetime
from types_ import Callable, DatabaseCursor, Logger
import threading

def save_validation_errors(
        validation_results: list[dict], 
        cursor: 'DatabaseCursor', 
        logger: Logger,
        make_cid: Callable,
        sql_string: str 
        ) -> int:
    """Save any validation errors found to the error database."""
    error_count = 0

    insert_batch = []
    for result in validation_results:
        gnis = result['gnis']
        citation_cid = result['cid']

        # Check each validation type for errors
        errors = {
            'geography': result.get('geography', {}),
            'type': result.get('type', {}),
            'section': result.get('section', {}),
            'date': result.get('date', {}),
            'format': result.get('format', {})
        }

        # Only save if there are errors
        if any([errors.values()]):
            # Collect error messages
            error_messages = []
            for error, msg in errors.items():
                if msg is None:
                    continue
                else:
                    error_messages.append(f"{error.capitalize()}: {msg.get('message', 'Unknown error')}")

            # Determine severity based on number and type of errors.
            num_errors = sum(len(error_messages))
            critical_errors = errors['geography'] or errors['type']

            row = {
                "cid": None,  # Placeholder for CID generation
                "citation_cid": citation_cid,
                "gnis": gnis,
                "geography_error": errors['geography'],
                "type_error": errors['type'],
                "section_error": errors['section'],
                "date_error": errors['date'],
                "format_error": errors['format'],
                "severity": 5 if critical_errors else num_errors,
                "error_message": "; ".join(error_messages),
                "updated_at": f"{datetime.now().isoformat()}"
            }
            # Generate CID based on the merged dictionary values.
            # NOTE Order matters here for consistent CID generation.
            row['cid'] = make_cid("".join(str(v) for v in row.values()))
            insert_batch.append(row)

    if insert_batch: # TODO Move this into it's own function and test it
        try:
            cursor.begin()
            # Insert error record into database
            cursor.sql(sql_string, insert_batch)
            cursor.commit()
            error_count += num_errors
        except Exception as e:
            logger.error(f"Failed to save error to database: {e}")
    return

    # return error_count
    # def _save_validation_errors(
    #     error_db, 
    #     errors: list[dict], 
    #     logger: Logger
    #     ) -> int:
    #     """
    #     Save validation errors to the error_reports table.
    #     """
    #     error_count = 0
    #     lock = threading.Lock()

    #     for error in errors:
    #     citation_cid = error.get('citation_cid')
    #     gnis = error.get('gnis')
    #     geography_error = error.get('geography_error')
    #     type_error = error.get('type_error')
    #     section_error = error.get('section_error')
    #     date_error = error.get('date_error')
    #     format_error = error.get('format_error')
    #     severity = error.get('severity')
    #     report_text = error.get('report_text', '')

    #     try:
    #         with lock:
    #         with error_db.cursor() as cursor:
    #             cursor.execute("""
    #             INSERT INTO error_reports (
    #                 cid,
    #                 citation_cid, 
    #                 gnis, 
    #                 geography_error, 
    #                 type_error, 
    #                 section_error, 
    #                 date_error, 
    #                 format_error,
    #                 severity,
    #                 report_text
    #             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    #             """, (
    #             error.get('cid'),
    #             citation_cid,
    #             gnis,
    #             geography_error,
    #             type_error,
    #             section_error,
    #             date_error,
    #             format_error,
    #             severity,
    #             report_text
    #             ))
    #         error_count += 1
    #     except Exception as e:
    #         logger.error(f"Failed to save error to error_reports: {e}")

    #     return error_count