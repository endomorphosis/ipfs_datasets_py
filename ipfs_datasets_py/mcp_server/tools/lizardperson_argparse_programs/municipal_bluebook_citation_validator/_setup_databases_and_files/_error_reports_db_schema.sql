CREATE TABLE IF NOT EXISTS error_reports (
    cid VARCHAR(255) PRIMARY KEY,
    report_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_error_reports_gnis ON error_reports(gnis);
CREATE INDEX idx_error_reports_citation_cid ON error_reports(citation_cid);
CREATE INDEX idx_error_reports_severity ON error_reports(severity);