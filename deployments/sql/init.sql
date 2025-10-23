-- Initialize GraphRAG database schema
-- This script sets up the necessary tables for metadata and analytics

-- Create database (if not exists)
CREATE DATABASE IF NOT EXISTS graphrag_db;

-- Connect to the database
\c graphrag_db;

-- Create extension for UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users and authentication
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) DEFAULT 'user' CHECK (role IN ('user', 'admin', 'analyst')),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP WITH TIME ZONE
);

-- Website processing jobs
CREATE TABLE IF NOT EXISTS processing_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id),
    url TEXT NOT NULL,
    status VARCHAR(50) DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    processing_mode VARCHAR(50) DEFAULT 'balanced',
    include_media BOOLEAN DEFAULT true,
    archive_services TEXT[] DEFAULT ARRAY['ia', 'is'],
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    progress DECIMAL(5,2) DEFAULT 0.0,
    
    -- Results metadata
    entities_extracted INTEGER DEFAULT 0,
    relationships_found INTEGER DEFAULT 0,
    content_pieces_processed INTEGER DEFAULT 0,
    media_files_processed INTEGER DEFAULT 0,
    quality_score DECIMAL(5,2),
    
    -- Resource usage
    processing_time_seconds INTEGER,
    memory_peak_mb INTEGER,
    storage_used_mb INTEGER
);

-- Website content metadata
CREATE TABLE IF NOT EXISTS website_content (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID REFERENCES processing_jobs(id),
    url TEXT NOT NULL,
    content_type VARCHAR(100) NOT NULL,
    title TEXT,
    content_length INTEGER,
    language VARCHAR(10),
    extracted_text TEXT,
    entities JSONB,
    relationships JSONB,
    embeddings_path TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Knowledge graph entities
CREATE TABLE IF NOT EXISTS kg_entities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID REFERENCES processing_jobs(id),
    name VARCHAR(500) NOT NULL,
    entity_type VARCHAR(100) NOT NULL,
    description TEXT,
    confidence_score DECIMAL(5,2),
    source_url TEXT,
    source_content_id UUID REFERENCES website_content(id),
    properties JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Knowledge graph relationships
CREATE TABLE IF NOT EXISTS kg_relationships (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID REFERENCES processing_jobs(id),
    source_entity_id UUID REFERENCES kg_entities(id),
    target_entity_id UUID REFERENCES kg_entities(id),
    relationship_type VARCHAR(200) NOT NULL,
    confidence_score DECIMAL(5,2),
    evidence TEXT,
    properties JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- System metrics for monitoring
CREATE TABLE IF NOT EXISTS system_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metric_type VARCHAR(100) NOT NULL,
    metric_name VARCHAR(200) NOT NULL,
    metric_value DECIMAL(15,4),
    metadata JSONB,
    
    INDEX idx_metrics_timestamp (timestamp),
    INDEX idx_metrics_type_name (metric_type, metric_name)
);

-- User activity logs
CREATE TABLE IF NOT EXISTS user_activity (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id),
    action VARCHAR(200) NOT NULL,
    resource_type VARCHAR(100),
    resource_id UUID,
    ip_address INET,
    user_agent TEXT,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_activity_user (user_id),
    INDEX idx_activity_timestamp (created_at)
);

-- Search queries for analytics
CREATE TABLE IF NOT EXISTS search_queries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id),
    job_id UUID REFERENCES processing_jobs(id),
    query TEXT NOT NULL,
    query_type VARCHAR(50) DEFAULT 'semantic',
    results_count INTEGER,
    response_time_ms INTEGER,
    satisfaction_score DECIMAL(3,2), -- User feedback on results
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_queries_user (user_id),
    INDEX idx_queries_job (job_id),
    INDEX idx_queries_timestamp (created_at)
);

-- Archive metadata
CREATE TABLE IF NOT EXISTS archive_metadata (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID REFERENCES processing_jobs(id),
    original_url TEXT NOT NULL,
    archive_service VARCHAR(50) NOT NULL,
    archive_url TEXT,
    archive_timestamp TIMESTAMP WITH TIME ZONE,
    content_hash VARCHAR(128),
    file_size_bytes BIGINT,
    status VARCHAR(50) DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_jobs_user_status ON processing_jobs(user_id, status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON processing_jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_content_job ON website_content(job_id);
CREATE INDEX IF NOT EXISTS idx_content_type ON website_content(content_type);
CREATE INDEX IF NOT EXISTS idx_entities_job ON kg_entities(job_id);
CREATE INDEX IF NOT EXISTS idx_entities_type ON kg_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_relationships_job ON kg_relationships(job_id);
CREATE INDEX IF NOT EXISTS idx_archive_job ON archive_metadata(job_id);

-- Create default admin user (password: admin - CHANGE IN PRODUCTION)
INSERT INTO users (username, email, password_hash, role) 
VALUES (
    'admin', 
    'admin@example.com', 
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj78.1tIJHfS', -- bcrypt hash of 'admin'
    'admin'
) ON CONFLICT (username) DO NOTHING;

-- Create sample user (password: demo - CHANGE IN PRODUCTION)
INSERT INTO users (username, email, password_hash, role) 
VALUES (
    'demo', 
    'demo@example.com', 
    '$2b$12$92hKmITPNSPkY8Z1fWp1C.2BzGQN/kQOKCz7OLx2yDqzZJNZWBtoW', -- bcrypt hash of 'demo'
    'user'
) ON CONFLICT (username) DO NOTHING;