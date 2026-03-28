"""
Migration Runner - Apply database migrations for spreadsheet support.

Run with: python scripts/migrations/005_add_spreadsheets.py
"""

import asyncio
import asyncpg
import os
from pathlib import Path


MIGRATION_SQL = """
-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Table: spreadsheets
CREATE TABLE IF NOT EXISTS spreadsheets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    description TEXT,
    source_path TEXT,
    source_type VARCHAR(20) DEFAULT 'file',
    file_type VARCHAR(10),
    sheet_name TEXT,
    sheet_index INTEGER DEFAULT 0,
    row_count INTEGER DEFAULT 0,
    column_count INTEGER DEFAULT 0,
    column_headers JSONB DEFAULT '[]'::jsonb,
    column_types JSONB DEFAULT '{}'::jsonb,
    primary_key_columns JSONB DEFAULT '[]'::jsonb,
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'ready', 'error')),
    error_message TEXT,
    processed_at TIMESTAMPTZ,
    qdrant_collection TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    tags JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(255)
);

-- Table: spreadsheet_rows
CREATE TABLE IF NOT EXISTS spreadsheet_rows (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    spreadsheet_id UUID NOT NULL REFERENCES spreadsheets(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    row_hash TEXT,
    row_data JSONB NOT NULL,
    embedding_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(spreadsheet_id, row_index)
);

-- Table: spreadsheet_cells
CREATE TABLE IF NOT EXISTS spreadsheet_cells (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    spreadsheet_id UUID NOT NULL REFERENCES spreadsheets(id) ON DELETE CASCADE,
    row_id UUID REFERENCES spreadsheet_rows(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    column_index INTEGER NOT NULL,
    column_name TEXT,
    cell_value TEXT,
    cell_type VARCHAR(20),
    raw_value TEXT,
    formula TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    UNIQUE(spreadsheet_id, row_index, column_index)
);

-- Table: spreadsheet_embeddings
CREATE TABLE IF NOT EXISTS spreadsheet_embeddings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    spreadsheet_id UUID NOT NULL REFERENCES spreadsheets(id) ON DELETE CASCADE,
    entity_type VARCHAR(20) NOT NULL CHECK (entity_type IN ('row', 'cell', 'chunk')),
    entity_id UUID,
    qdrant_point_id TEXT NOT NULL,
    qdrant_collection TEXT NOT NULL,
    embedding_model VARCHAR(100),
    embedding_dim INTEGER,
    embedded_content TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(qdrant_collection, qdrant_point_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_spreadsheets_name ON spreadsheets(name);
CREATE INDEX IF NOT EXISTS idx_spreadsheets_status ON spreadsheets(status);
CREATE INDEX IF NOT EXISTS idx_spreadsheets_source_type ON spreadsheets(source_type);
CREATE INDEX IF NOT EXISTS idx_spreadsheets_created_at ON spreadsheets(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_spreadsheet_rows_spreadsheet_id ON spreadsheet_rows(spreadsheet_id);
CREATE INDEX IF NOT EXISTS idx_spreadsheet_rows_row_index ON spreadsheet_rows(spreadsheet_id, row_index);
CREATE INDEX IF NOT EXISTS idx_spreadsheet_rows_data ON spreadsheet_rows USING GIN(row_data);
CREATE INDEX IF NOT EXISTS idx_spreadsheet_rows_hash ON spreadsheet_rows(row_hash);
CREATE INDEX IF NOT EXISTS idx_spreadsheet_cells_spreadsheet_id ON spreadsheet_cells(spreadsheet_id);
CREATE INDEX IF NOT EXISTS idx_spreadsheet_cells_location ON spreadsheet_cells(spreadsheet_id, row_index, column_index);
CREATE INDEX IF NOT EXISTS idx_spreadsheet_embeddings_spreadsheet_id ON spreadsheet_embeddings(spreadsheet_id);
CREATE INDEX IF NOT EXISTS idx_spreadsheet_embeddings_qdrant ON spreadsheet_embeddings(qdrant_collection, qdrant_point_id);

-- Triggers
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

-- Mark migration complete
INSERT INTO system_state (key, value) 
VALUES ('migration_005_spreadsheets', 'complete')
ON CONFLICT (key) DO UPDATE SET value = 'complete', updated_at = NOW();
"""


async def run_migration(database_url: str):
    print("Running migration: Add spreadsheet tables...")
    
    try:
        conn = await asyncpg.connect(database_url)
        
        # Check if migration already ran
        existing = await conn.fetchval(
            "SELECT value FROM system_state WHERE key = 'migration_005_spreadsheets'"
        )
        
        if existing == 'complete':
            print("⚠️  Migration already applied. Skipping.")
            await conn.close()
            return
        
        await conn.execute(MIGRATION_SQL)
        print("✅ Migration completed successfully")
        
        await conn.close()
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise


if __name__ == "__main__":
    db_url = os.environ.get(
        "DATABASE_URL", 
        "postgresql://temporal:temporal@localhost:5432/orchestrator"
    )
    asyncio.run(run_migration(db_url))
