"""Backup Postgres database using asyncpg (fallback when pg_dump unavailable)."""
import asyncio
import asyncpg
import os
import json
from datetime import datetime
from pathlib import Path

BACKUP_DIR = Path(__file__).parent.parent / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://temporal:temporal@localhost:5432/orchestrator")

async def backup_database():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"postgres_backup_{timestamp}.sql"
    
    print(f"Connecting to database...")
    conn = await asyncpg.connect(DATABASE_URL)
    
    lines = []
    lines.append("-- PostgreSQL Backup")
    lines.append(f"-- Generated: {datetime.now().isoformat()}")
    lines.append("-- Database: orchestrator")
    lines.append("")
    
    # Get all tables
    tables = await conn.fetch("""
        SELECT tablename FROM pg_tables 
        WHERE schemaname = 'public' 
        ORDER BY tablename
    """)
    
    print(f"Found {len(tables)} tables to backup")
    
    for row in tables:
        table_name = row['tablename']
        print(f"  Backing up table: {table_name}")
        
        # Get table structure
        try:
            create_stmt = await conn.fetchval(f"""
                SELECT 'CREATE TABLE ' || tablename || ' (' ||
                string_agg(column_name || ' ' || data_type || 
                    CASE WHEN character_maximum_length IS NOT NULL 
                         THEN '(' || character_maximum_length || ')' 
                         ELSE '' END ||
                    CASE WHEN is_nullable = 'NO' THEN ' NOT NULL' ELSE '' END,
                    ', ' ORDER BY ordinal_position) || ');'
                FROM information_schema.columns
                WHERE table_name = $1 AND table_schema = 'public'
            """, table_name)
            
            if create_stmt:
                lines.append(f"\n-- Table: {table_name}")
                lines.append(f"DROP TABLE IF EXISTS {table_name} CASCADE;")
                lines.append(create_stmt)
        except Exception as e:
            lines.append(f"\n-- Could not get structure for {table_name}: {e}")
        
        # Get row count
        count = await conn.fetchval(f'SELECT COUNT(*) FROM "{table_name}"')
        lines.append(f"-- Row count: {count}")
        
        if count > 0 and count < 10000:  # Only backup data for small tables
            rows = await conn.fetch(f'SELECT * FROM "{table_name}"')
            if rows:
                cols = list(rows[0].keys())
                for r in rows:
                    values = []
                    for c in cols:
                        v = r[c]
                        if v is None:
                            values.append('NULL')
                        elif isinstance(v, str):
                            values.append(f"'{v.replace(chr(39), chr(39)+chr(39))}'")
                        elif isinstance(v, (int, float)):
                            values.append(str(v))
                        elif isinstance(v, bytes):
                            values.append(f"'{v.hex()}'::bytea")
                        else:
                            values.append(f"'{str(v).replace(chr(39), chr(39)+chr(39))}'")
                    lines.append(f"INSERT INTO {table_name} ({', '.join(cols)}) VALUES ({', '.join(values)});")
    
    await conn.close()
    
    # Write backup file
    with open(backup_file, 'w') as f:
        f.write('\n'.join(lines))
    
    print(f"✅ Postgres backup saved: {backup_file}")
    return str(backup_file)

if __name__ == "__main__":
    asyncio.run(backup_database())
