-- Database initialization schema (portable)
-- This file is intentionally minimal and uses broadly compatible SQL.

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE,
    email TEXT UNIQUE,
    password_hash TEXT,
    role TEXT,
    is_active INTEGER,
    created_at TEXT,
    updated_at TEXT,
    last_login TEXT
);

CREATE TABLE IF NOT EXISTS processing_jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    url TEXT,
    status TEXT,
    processing_mode TEXT,
    include_media INTEGER,
    created_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    error_message TEXT,
    progress REAL,
    entities_extracted INTEGER,
    relationships_found INTEGER,
    content_pieces_processed INTEGER,
    media_files_processed INTEGER,
    quality_score REAL,
    processing_time_seconds INTEGER,
    memory_peak_mb INTEGER,
    storage_used_mb INTEGER
);

CREATE TABLE IF NOT EXISTS website_content (
    id TEXT PRIMARY KEY,
    job_id TEXT,
    url TEXT,
    content_type TEXT,
    title TEXT,
    content_length INTEGER,
    language TEXT,
    extracted_text TEXT,
    entities TEXT,
    relationships TEXT,
    embeddings_path TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS kg_entities (
    id TEXT PRIMARY KEY,
    job_id TEXT,
    name TEXT,
    entity_type TEXT,
    description TEXT,
    confidence_score REAL,
    source_url TEXT,
    source_content_id TEXT,
    properties TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS kg_relationships (
    id TEXT PRIMARY KEY,
    job_id TEXT,
    source_entity_id TEXT,
    target_entity_id TEXT,
    relationship_type TEXT,
    confidence_score REAL,
    evidence TEXT,
    properties TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS system_metrics (
    id TEXT PRIMARY KEY,
    timestamp TEXT,
    metric_type TEXT,
    metric_name TEXT,
    metric_value REAL,
    metadata TEXT
);
