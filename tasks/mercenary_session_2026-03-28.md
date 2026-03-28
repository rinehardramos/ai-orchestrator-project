# Mercenary Marketplace - Session Summary

**Date**: 2026-03-28

## Overview

Created and deployed the "Agent Mercenaries Marketplace" - a bounty-based platform where users post tasks with price/duration and AI agents automatically claim and complete them.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Vercel        │     │   Railway       │     │   Supabase      │
│   (Frontend)    │────▶│   (FastAPI)     │────▶│   (PostgreSQL)  │
│   Next.js 16.2  │     │   Port: 8001    │     │   500 MB free   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Completed

### Frontend (Submodule)
- Created `src/mercenary/web` as independent git submodule
- Repo: https://github.com/rinehardramos/mercenary-web
- Next.js 16.2.1 (fixed CVE-2025-55184, CVE-2025-67779)
- Pages: Landing, Login, Signup, Dashboard, Agents
- Vercel deployment ready

### Backend
- FastAPI with JWT authentication
- Bounty CRUD endpoints
- Agent matching algorithm (40% price, 25% skill, 20% duration, 15% reputation)
- Wallet/balance system
- Database models and repositories

### Deployment
- Railway configuration (`railway.toml`)
- Supabase database setup guide
- Environment variables documented
- CORS configured for production domains

### Seeded Agents
| Name | Model | Specialization | Cost |
|------|-------|----------------|------|
| Shadow | claude-sonnet-4 | Coding | $0.50 |
| Viper | gemini-2.5-flash | Research | $0.20 |
| Ghost | gpt-4o | General | $0.35 |
| Phantom | mistral-nemo | Writing | $0.15 |
| Reaper | claude-opus-4 | Expert | $1.00 |

## Files Created/Modified

### New Files
- `src/mercenary/web/` - Submodule (separate repo)
- `src/mercenary/railway.toml` - Railway deployment config
- `src/mercenary/RAILWAY_DEPLOY.md` - Deployment guide
- `src/mercenary/SUPABASE_DEPLOY.md` - Database setup guide
- `.gitmodules` - Submodule tracking

### Modified
- `src/mercenary/main.py` - Added CORS for production domains
- `src/mercenary/config.py` - Support Railway's PORT env var
- `src/mercenary/docker-compose.yml` - Already existed

## Deployment Steps

1. **Supabase**: Create project, get connection string
2. **Railway**: 
   ```bash
   railway login
   railway init
   railway up
   railway variables set MERCENARY_DATABASE_URL="..."
   railway variables set MERCENARY_JWT_SECRET="$(openssl rand -hex 32)"
   railway variables set MERCENARY_SECRET_KEY="$(openssl rand -hex 32)"
   ```
3. **Vercel**: Import `rinehardramos/mercenary-web`, set `NEXT_PUBLIC_API_URL`

## Not Started

- Week 2: Temporal integration for bounty execution
- Week 4: Stripe payments, production polish

## Security Fixes

- Upgraded Next.js 14.2.0 → 16.2.1
- Fixed CVE-2025-55184 (DoS via Image Optimizer)
- Fixed CVE-2025-67779 (HTTP request smuggling)
