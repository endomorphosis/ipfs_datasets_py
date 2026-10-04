CREATE TABLE IF NOT EXISTS errors (
    cid VARCHAR(255) PRIMARY KEY, -- from all other stats, including created_at.
    citation_cid VARCHAR(255) NOT NULL,
    gnis INTEGER NOT NULL,
    geography_error VARCHAR(255) NOT NULL,
    type_error VARCHAR(255) NOT NULL,
    section_error VARCHAR(255) NOT NULL,
    date_error VARCHAR(255) NOT NULL,
    format_error VARCHAR(255) NOT NULL,
    severity INTEGER CHECK (severity IN (1, 2, 3, 4, 5)), -- Severity levels: 1 (low) to 5 (critical)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Create indexes for better query performance
CREATE INDEX idx_errors_gnis ON errors(gnis);
CREATE INDEX idx_errors_citation_cid ON errors(citation_cid);
CREATE INDEX idx_errors_severity ON errors(severity);