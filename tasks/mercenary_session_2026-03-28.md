# Mercenary Marketplace - Session Summary

**Date**: 2026-03-28

## Overview

Created the "Agent Mercenaries Marketplace" - a bounty-based platform where users post tasks with price/duration and AI agents automatically claim and complete them.

## Architecture - Separate Repositories

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         mercs.tech Platform                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐   │
│  │ mercenary-web   │     │ mercenary-api   │     │ Supabase        │   │
│  │ (Vercel)        │────▶│ (Railway)       │────▶│ (PostgreSQL)    │   │
│  │ Next.js 16.2    │     │ FastAPI         │     │ 500 MB free     │   │
│  └─────────────────┘     └────────┬────────┘     └─────────────────┘   │
│                                   │                                     │
│                                   │ HTTP API (submit tasks)              │
│                                   ▼                                     │
│  ┌────────────────────────────────────────────────────────────────────┐│
│  │ ai-orchestrator-project (Core Infrastructure)                      ││
│  │ - Temporal workflows                                                ││
│  │ - LiteLLM proxy                                                    ││
│  │ - Worker nodes                                                     ││
│  │ - Qdrant vector DB                                                 ││
│  └────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

## Repositories

| Repo | Platform | Purpose |
|------|----------|---------|
| [mercenary-web](https://github.com/rinehardramos/mercenary-web) | Vercel | Frontend (Next.js) |
| [mercenary-api](https://github.com/rinehardramos/mercenary-api) | Railway | Backend (FastAPI) |
| [ai-orchestrator-project](https://github.com/rinehardramos/ai-orchestrator-project) | Self-hosted | Core infrastructure |

## Completed

### Frontend (mercenary-web)
- Next.js 16.2.1 (fixed CVE-2025-55184, CVE-2025-67779)
- Pages: Landing, Login, Signup, Dashboard, Agents
- Vercel deployment ready

### Backend (mercenary-api)
- FastAPI with JWT authentication
- Bounty CRUD endpoints
- Agent matching algorithm (40% price, 25% skill, 20% duration, 15% reputation)
- Wallet/balance system
- Railway + Supabase ready

### Seeded Agents
| Name | Model | Specialization | Cost |
|------|-------|----------------|------|
| Shadow | claude-sonnet-4 | Coding | $0.50 |
| Viper | gemini-2.5-flash | Research | $0.20 |
| Ghost | gpt-4o | General | $0.35 |
| Phantom | mistral-nemo | Writing | $0.15 |
| Reaper | claude-opus-4 | Expert | $1.00 |

## Deployment Steps

### 1. Supabase (Database)
1. Create project at https://supabase.com
2. Get connection string: Settings > Database > Connection string (pooler)

### 2. Railway (Backend)
```bash
# Clone the backend repo
git clone https://github.com/rinehardramos/mercenary-api
cd mercenary-api

# Deploy
railway login
railway init
railway up

# Set environment variables
railway variables set DATABASE_URL="postgresql://..."
railway variables set JWT_SECRET="$(openssl rand -hex 32)"
railway variables set SECRET_KEY="$(openssl rand -hex 32)"
railway variables set CORE_API_URL="https://your-core-api.com/api/internal"
railway variables set CORE_API_KEY="your-api-key"
```

### 3. Vercel (Frontend)
1. Import `rinehardramos/mercenary-web` in Vercel
2. Set `NEXT_PUBLIC_API_URL=https://<railway-app>.up.railway.app`

## Not Started

- Temporal integration for bounty execution (in mercenary-api)
- Stripe payments
- Production polish
