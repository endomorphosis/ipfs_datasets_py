CREATE TABLE IF NOT EXISTS errors (
    cid VARCHAR(255) PRIMARY KEY,
    citation_cid VARCHAR(255),
    gnis INTEGER,
    geography_error BOOLEAN,
    type_error BOOLEAN,
    section_error BOOLEAN,
    date_error BOOLEAN,
    format_error BOOLEAN,
    severity INTEGER CHECK (severity IN (1, 2, 3, 4, 5)), -- Severity levels: 1 (low) to 5 (critical)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Create indexes for better query performance
CREATE INDEX idx_errors_gnis ON errors(gnis);
CREATE INDEX idx_errors_citation_cid ON errors(citation_cid);
CREATE INDEX idx_errors_severity ON errors(severity);