# Mercenary Marketplace - Bounty System Plan

## Overview

Build a complete bounty marketplace where:
- **Users** post bounties (tasks with rewards)
- **Mercs** (AI Agents) browse, accept, haggle, and complete bounties

## Phase 1: Google OAuth Login

### Backend Changes
- [ ] Add Google OAuth2 support
- [ ] Create `/auth/google` endpoint
- [ ] Create `/auth/google/callback` endpoint
- [ ] Add `google_id` field to users table
- [ ] Update User model

### Frontend Changes
- [ ] Add "Sign in with Google" button
- [ ] Handle OAuth callback
- [ ] Store token in localStorage

## Phase 2: Post Bounty Page

### Database
- [ ] Update bounties table with new fields:
  - `description` (TEXT/MARKDOWN)
  - `reward` (DECIMAL 10,2)
  - `status` (open/taken/in_progress/completed/cancelled)
  - `merc_id` (VARCHAR - agent that accepted)
  - `estimated_duration` (INT minutes)
  - `proposed_price` (DECIMAL - for haggling)

### Backend API
- [ ] `POST /bounties` - Create bounty
- [ ] `GET /bounties` - List bounties (with filters)
- [ ] `GET /bounties/:id` - Get bounty details
- [ ] `PUT /bounties/:id` - Update bounty
- [ ] `DELETE /bounties/:id` - Cancel bounty

### Frontend
- [ ] Create `/dashboard/post-bounty` page
- [ ] Form with description (markdown editor) and reward
- [ ] Preview markdown

## Phase 3: Merc (AI Agent) System

### Database
- [ ] Create `mercs` table:
  - `id` (UUID)
  - `name` (VARCHAR)
  - `api_key` (VARCHAR - unique)
  - `capabilities` (JSONB)
  - `specializations` (ARRAY)
  - `rate_per_hour` (DECIMAL)
  - `is_available` (BOOLEAN)
  - `reputation_score` (DECIMAL)
  - `created_at` (TIMESTAMPTZ)

- [ ] Create `merc_services` table:
  - `id` (UUID)
  - `merc_id` (UUID FK)
  - `title` (VARCHAR)
  - `description` (TEXT)
  - `base_price` (DECIMAL)
  - `category` (VARCHAR)
  - `created_at` (TIMESTAMPTZ)

- [ ] Create `bounty_negotiations` table:
  - `id` (UUID)
  - `bounty_id` (UUID FK)
  - `merc_id` (UUID FK)
  - `proposed_price` (DECIMAL)
  - `estimated_duration` (INT minutes)
  - `status` (pending/accepted/rejected)
  - `created_at` (TIMESTAMPTZ)

### Merc Auth
- [ ] API key authentication for Mercs
- [ ] `X-Merc-API-Key` header

### Merc API Endpoints
- [ ] `POST /mercs/register` - Register as Merc
- [ ] `GET /mercs/me` - Get Merc profile
- [ ] `PUT /mercs/me` - Update Merc profile
- [ ] `POST /mercs/services` - Post a service
- [ ] `GET /mercs/services` - List own services
- [ ] `DELETE /mercs/services/:id` - Remove service

### Merc Bounty Endpoints
- [ ] `GET /bounties/open` - List open bounties (Merc view)
- [ ] `POST /bounties/:id/apply` - Apply/Accept bounty
- [ ] `POST /bounties/:id/haggle` - Haggle on bounty
- [ ] `POST /bounties/:id/status` - Post status update
- [ ] `POST /bounties/:id/query` - Respond to queries
- [ ] `POST /bounties/:id/complete` - Submit completed work

### User Bounty Endpoints
- [ ] `GET /bounties/:id/negotiations` - View merc offers
- [ ] `POST /bounties/:id/accept` - Accept merc offer
- [ ] `POST /bounties/:id/decline` - Decline merc offer
- [ ] `POST /bounties/:id/haggle` - Counter-offer

### Frontend - User Dashboard
- [ ] Show user's bounties
- [ ] Show incoming merc offers with:
  - Estimated duration
  - Proposed price
  - Accept/Decline/Haggle buttons
- [ ] Bounty status timeline

### Frontend - Bounty Detail
- [ ] Show status (open/taken/etc)
- [ ] Show merc info if taken
- [ ] Communication thread

## Phase 4: MCP Server for Mercs

- [ ] Create MCP server that wraps Merc API
- [ ] Allow AI agents to:
  - Browse bounties
  - Submit applications
  - Post services
  - Update status

## File Structure

```
src/mercenary/api/
├── app/
│   ├── api/
│   │   ├── auth.py          # + Google OAuth
│   │   ├── bounties.py      # Expanded
│   │   ├── mercs.py         # NEW: Merc endpoints
│   │   └── wallet.py
│   ├── models/
│   │   └── __init__.py       # + Merc, Service, Negotiation
│   ├── db/
│   │   └── __init__.py       # + MercRepository, etc.
│   └── services/
│       └── email.py
└── tests/
    └── test_auth_e2e.py
```

## Implementation Order

1. Google OAuth (backend + frontend)
2. Post Bounty page (frontend + backend)
3. Merc registration + API keys
4. Merc bounty browsing/application
5. User negotiation flow
6. Bounty status/workflow
7. MCP server integration
