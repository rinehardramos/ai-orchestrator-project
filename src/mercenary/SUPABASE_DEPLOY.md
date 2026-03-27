# Supabase Database Setup

## 1. Create Supabase Project

1. Go to https://supabase.com and create a new project
2. Note your project reference (e.g., `abcdefghijklmnop`)
3. Save the database password

## 2. Get Connection Strings

In Supabase dashboard: **Settings > Database > Connection string**

### For Railway/Production (Direct connection):
```
postgresql://postgres.[PROJECT-REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres
```

### For Local Development:
```
postgresql://postgres:[PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres
```

## 3. Set Environment Variables

### Railway:
```bash
railway variables set MERCENARY_DATABASE_URL="postgresql://postgres.[PROJECT-REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres"
```

### Local (.env):
```
MERCENARY_DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres
```

## 4. Enable pgvector (Optional)

If you need vector search for agent matching:
1. Go to **Database > Extensions**
2. Enable `vector` extension

## 5. Tables

Tables are auto-created on first startup via `init_database()` in `db/connection.py`.

To verify:
```sql
SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';
```

## Free Tier Limits

| Resource | Limit |
|----------|-------|
| Database size | 500 MB |
| Bandwidth | 5 GB/month |
| API requests | 500K/month |
| Concurrent connections | 60 (direct), 200 (pooler) |

## Troubleshooting

### Connection refused
- Use pooler connection string for serverless/Railway
- Check if IPv4 is enabled (Supabase > Settings > Database > IPv4)

### SSL error
Add `?sslmode=require` to connection string:
```
postgresql://...@.../postgres?sslmode=require
