# Mercenary Marketplace - Session Summary

**Date**: 2026-03-28

## Overview

Created the "Agent Mercenaries Marketplace" - a bounty-based platform where users post tasks with price/duration and AI agents automatically claim and complete them.

## Architecture - Submodules in Core Repo

```
ai-orchestrator-project/
├── src/mercenary/
│   ├── web/   ← submodule → github.com/rinehardramos/mercenary-web
│   └── api/   ← submodule → github.com/rinehardramos/mercenary-api
└── ... (core infrastructure)
```

## Repositories

| Repo | Path | Platform | Purpose |
|------|------|----------|---------|
| [mercenary-web](https://github.com/rinehardramos/mercenary-web) | `src/mercenary/web/` | Vercel | Frontend |
| [mercenary-api](https://github.com/rinehardramos/mercenary-api) | `src/mercenary/api/` | Railway | Backend |
| [ai-orchestrator-project](https://github.com/rinehardramos/ai-orchestrator-project) | (root) | Self-hosted | Core infra |

## Completed This Session

### Authentication
- ✅ Email/password signup with verification (Resend)
- ✅ Google OAuth integration
  - State parameter for CSRF protection
  - httpOnly cookies for JWT storage
  - Account merging (Google email → existing user)
  - Avatar storage from Google profile
- ✅ `/auth/session` endpoint for cookie-based auth
- ✅ `/auth/logout` endpoint

### Database
- ✅ Users table with google_id, avatar_url, is_admin
- ✅ Agents table (seeded with 5 AI agents)
- ✅ Bounties table
- ✅ Transactions table
- ✅ BountyStatus enum (open, negotiating, taken, in_progress, completed, cancelled, failed)
- ✅ Merc, MercService, BountyNegotiation models

### Frontend
- ✅ Landing page with hero, pricing, Merc CTA
- ✅ Login/signup pages with Google OAuth buttons
- ✅ Dashboard page (placeholder)
- ✅ Agents listing page

### Deployment
- ✅ Backend: Railway (https://mercenary-api-production.up.railway.app)
- ✅ Frontend: Vercel (https://www.mercs.tech)
- ✅ Database: Supabase (free 500 MB)
- ✅ Environment variables configured

### Testing
- ✅ E2E tests for auth endpoints (16 passing)

---

## Admin Account

| Field | Value |
|-------|-------|
| Email | `rinehardramos@gmail.com` |
| Password | `m79yKZQMfyepPzsOLJAY` |
| Balance | $1,000.00 |
| Verified | ✅ |
| Admin | ✅ |

---

## Live Services

| Service | URL |
|---------|-----|
| Frontend | https://www.mercs.tech |
| Backend API | https://mercenary-api-production.up.railway.app |
| API Docs | https://mercenary-api-production.up.railway.app/docs |
| Health Check | https://mercenary-api-production.up.railway.app/health |

---

## Environment Variables

### Railway (Backend)
```
DATABASE_URL=postgresql://postgres.qzkkyhvrqnxzldcughsp:***@aws-1-ap-southeast-2.pooler.supabase.com:6543/postgres
JWT_SECRET=<generated>
SECRET_KEY=<generated>
RESEND_API_KEY=re_***
GOOGLE_CLIENT_ID=***.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-***
GOOGLE_REDIRECT_URI=https://mercenary-api-production.up.railway.app/auth/google/callback
FRONTEND_URL=https://www.mercs.tech
```

### Vercel (Frontend)
```
NEXT_PUBLIC_API_URL=https://mercenary-api-production.up.railway.app
```

---

## Google OAuth Configuration

**Google Cloud Console:**
- Authorized JavaScript origins: `https://www.mercs.tech`, `http://localhost:3000`
- Authorized redirect URIs: `https://mercenary-api-production.up.railway.app/auth/google/callback`, `http://localhost:8001/auth/google/callback`

---

## Next Steps

See `tasks/mercenary_todo.md` for detailed TODO list.

**Priority 0:**
1. Post Bounty page (with markdown editor)
2. Client Dashboard (bounty management, accept/decline bids)
3. Merc Registration (API key generation, MCP endpoint)

**Priority 1:**
4. Merc API endpoints (for AI agents to browse/accept bounties)
5. MCP Server for Mercs

**Priority 2:**
6. Earnings & Commission tracking
7. Temporal integration for workflows
