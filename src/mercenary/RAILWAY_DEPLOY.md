# Railway Deployment Guide

## Database: Supabase (Free 500 MB)

Use Supabase for the database (free tier has no time limit).

See [SUPABASE_DEPLOY.md](./SUPABASE_DEPLOY.md) for database setup.

## Prerequisites
- Railway account (https://railway.app)
- Railway CLI installed: `npm i -g @railway/cli`
- Supabase project created

## Deployment Steps

### 1. Login to Railway
```bash
railway login
```

### 2. Create a new project
```bash
railway init
# Select "Empty Project" and name it "mercenary-api"
```

### 3. Deploy the API
```bash
railway up
# Or link and deploy:
railway link
railway up
```

### 4. Set Environment Variables

```bash
# Database (from Supabase dashboard)
railway variables set MERCENARY_DATABASE_URL="postgresql://postgres.[PROJECT-REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres"

# Security
railway variables set MERCENARY_JWT_SECRET="<generate-32-char-secret>"
railway variables set MERCENARY_SECRET_KEY="<generate-32-char-secret>"

# Core API (optional)
railway variables set CORE_API_URL="https://your-core-api.com/api/internal"
railway variables set CORE_API_KEY="your-api-key"
```

Generate secrets:
```bash
openssl rand -hex 32
```

## Connect Frontend to Backend

Update the frontend environment variable in Vercel:

```
NEXT_PUBLIC_API_URL=https://<your-railway-app>.up.railway.app
```

## Monitoring

- View logs: `railway logs`
- View metrics: Railway dashboard > project > service > Metrics
- Health check: `https://<your-railway-app>.up.railway.app/health`
