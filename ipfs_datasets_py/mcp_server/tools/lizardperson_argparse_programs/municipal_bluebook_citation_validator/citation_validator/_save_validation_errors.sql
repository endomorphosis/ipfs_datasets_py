INSERT INTO errors (
    cid, 
    citation_cid, 
    gnis, 
    geography_error, 
    type_error, 
    section_error, 
    date_error, 
    format_error, 
    severity,
    error_message,
    updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?. ?, ?);