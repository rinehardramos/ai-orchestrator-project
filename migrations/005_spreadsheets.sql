-- =============================================================================
-- Migration: 005_spreadsheets.sql
-- Description: Add spreadsheet storage for hybrid Postgres+Qdrant access
-- Version: 1.0
-- Created: 2026-03-28
-- =============================================================================

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- Table: spreadsheets
-- Stores metadata about ingested spreadsheet files
-- =============================================================================
CREATE TABLE IF NOT EXISTS spreadsheets (
    -- Identity
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    description TEXT,
    
    -- Source information
    source_path TEXT,                    -- Original file path/URL
    source_type VARCHAR(20) DEFAULT 'file', -- 'file', 'gdrive', 'url'
    file_type VARCHAR(10),               -- xlsx, xls, csv, tsv
    sheet_name TEXT,                     -- For multi-sheet files, which sheet
    sheet_index INTEGER DEFAULT 0,       -- Sheet index for multi-sheet files
    
    -- Structure metadata
    row_count INTEGER DEFAULT 0,
    column_count INTEGER DEFAULT 0,
    column_headers JSONB DEFAULT '[]'::jsonb,    -- ["col1", "col2", ...]
    column_types JSONB DEFAULT '{}'::jsonb,      -- {"col1": "string", "col2": "number", ...}
    primary_key_columns JSONB DEFAULT '[]'::jsonb, -- Columns that act as primary keys
    
    -- Processing state
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'ready', 'error')),
    error_message TEXT,
    processed_at TIMESTAMPTZ,
    
    -- Vector storage reference
    qdrant_collection TEXT,              -- Name of Qdrant collection if embedded
    
    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb, -- Additional custom metadata
    tags JSONB DEFAULT '[]'::jsonb,     -- Tags for categorization
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(255)
);

-- =============================================================================
-- Table: spreadsheet_rows
-- Stores individual row data for structured querying
-- =============================================================================
CREATE TABLE IF NOT EXISTS spreadsheet_rows (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    spreadsheet_id UUID NOT NULL REFERENCES spreadsheets(id) ON DELETE CASCADE,
    
    -- Row identification
    row_index INTEGER NOT NULL,
    row_hash TEXT,                       -- Hash of row data for change detection
    
    -- Row data as JSONB for flexible querying
    row_data JSONB NOT NULL,             -- {"col1": "value1", "col2": 42, ...}
    
    -- Vector embedding reference
    embedding_id TEXT,                    -- Qdrant point ID if embedded
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(spreadsheet_id, row_index)
);

-- =============================================================================
-- Table: spreadsheet_cells
-- Optional: Individual cell storage for large spreadsheets with sparse data
-- =============================================================================
CREATE TABLE IF NOT EXISTS spreadsheet_cells (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    spreadsheet_id UUID NOT NULL REFERENCES spreadsheets(id) ON DELETE CASCADE,
    row_id UUID REFERENCES spreadsheet_rows(id) ON DELETE CASCADE,
    
    -- Cell location
    row_index INTEGER NOT NULL,
    column_index INTEGER NOT NULL,
    column_name TEXT,
    
    -- Cell value and type
    cell_value TEXT,
    cell_type VARCHAR(20),               -- string, number, boolean, date, formula, error
    raw_value TEXT,                      -- Original value before type conversion
    formula TEXT,                        -- Formula if applicable
    
    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,
    
    UNIQUE(spreadsheet_id, row_index, column_index)
);

-- =============================================================================
-- Table: spreadsheet_embeddings
-- Tracks which rows/cells have been embedded in Qdrant
-- =============================================================================
CREATE TABLE IF NOT EXISTS spreadsheet_embeddings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    spreadsheet_id UUID NOT NULL REFERENCES spreadsheets(id) ON DELETE CASCADE,
    
    -- What was embedded
    entity_type VARCHAR(20) NOT NULL CHECK (entity_type IN ('row', 'cell', 'chunk')),
    entity_id UUID,                       -- Reference to row or cell
    
    -- Embedding metadata
    qdrant_point_id TEXT NOT NULL,        -- Point ID in Qdrant
    qdrant_collection TEXT NOT NULL,      -- Collection name
    embedding_model VARCHAR(100),         -- Model used for embedding
    embedding_dim INTEGER,                -- Embedding dimensions
    
    -- Content that was embedded
    embedded_content TEXT,                -- The text that was embedded
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(qdrant_collection, qdrant_point_id)
);

-- =============================================================================
-- Indexes for performance
-- =============================================================================

-- Spreadsheet lookups
CREATE INDEX idx_spreadsheets_name ON spreadsheets(name);
CREATE INDEX idx_spreadsheets_status ON spreadsheets(status);
CREATE INDEX idx_spreadsheets_source_type ON spreadsheets(source_type);
CREATE INDEX idx_spreadsheets_created_at ON spreadsheets(created_at DESC);

-- Row queries
CREATE INDEX idx_spreadsheet_rows_spreadsheet_id ON spreadsheet_rows(spreadsheet_id);
CREATE INDEX idx_spreadsheet_rows_row_index ON spreadsheet_rows(spreadsheet_id, row_index);
CREATE INDEX idx_spreadsheet_rows_data ON spreadsheet_rows USING GIN(row_data);
CREATE INDEX idx_spreadsheet_rows_hash ON spreadsheet_rows(row_hash);

-- Cell queries
CREATE INDEX idx_spreadsheet_cells_spreadsheet_id ON spreadsheet_cells(spreadsheet_id);
CREATE INDEX idx_spreadsheet_cells_location ON spreadsheet_cells(spreadsheet_id, row_index, column_index);

-- Embedding lookups
CREATE INDEX idx_spreadsheet_embeddings_spreadsheet_id ON spreadsheet_embeddings(spreadsheet_id);
CREATE INDEX idx_spreadsheet_embeddings_qdrant ON spreadsheet_embeddings(qdrant_collection, qdrant_point_id);

-- =============================================================================
-- Trigger: Auto-update updated_at timestamp
-- =============================================================================
CREATE OR REPLACE FUNCTION update_spreadsheet_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_spreadsheets_updated_at ON spreadsheets;
CREATE TRIGGER update_spreadsheets_updated_at
    BEFORE UPDATE ON spreadsheets
    FOR EACH ROW
    EXECUTE FUNCTION update_spreadsheet_updated_at();

DROP TRIGGER IF EXISTS update_spreadsheet_rows_updated_at ON spreadsheet_rows;
CREATE TRIGGER update_spreadsheet_rows_updated_at
    BEFORE UPDATE ON spreadsheet_rows
    FOR EACH ROW
    EXECUTE FUNCTION update_spreadsheet_updated_at();

-- =============================================================================
-- Useful views
-- =============================================================================

-- View: Spreadsheet summary
CREATE OR REPLACE VIEW spreadsheet_summary AS
SELECT 
    s.id,
    s.name,
    s.source_path,
    s.file_type,
    s.sheet_name,
    s.row_count,
    s.column_count,
    s.status,
    s.qdrant_collection,
    s.created_at,
    COUNT(sr.id) as stored_row_count,
    COUNT(se.id) as embedding_count
FROM spreadsheets s
LEFT JOIN spreadsheet_rows sr ON s.id = sr.spreadsheet_id
LEFT JOIN spreadsheet_embeddings se ON s.id = se.spreadsheet_id
GROUP BY s.id;

-- =============================================================================
-- Grant permissions
-- =============================================================================
GRANT ALL PRIVILEGES ON TABLE spreadsheets TO temporal;
GRANT ALL PRIVILEGES ON TABLE spreadsheet_rows TO temporal;
GRANT ALL PRIVILEGES ON TABLE spreadsheet_cells TO temporal;
GRANT ALL PRIVILEGES ON TABLE spreadsheet_embeddings TO temporal;
GRANT ALL PRIVILEGES ON SEQUENCE spreadsheets_id_seq TO temporal;

-- =============================================================================
-- Migration complete
-- =============================================================================
INSERT INTO system_state (key, value) 
VALUES ('migration_005_spreadsheets', 'complete')
ON CONFLICT (key) DO UPDATE SET value = 'complete', updated_at = NOW();
