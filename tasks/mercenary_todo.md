# Mercenary Marketplace - TODO

## Phase 1: Post Bounty Page

### Backend
- [ ] Create `POST /bounties` endpoint with `bounty_mode` (auto/bid)
- [ ] Add `bounty_mode` column to bounties table
- [ ] Add validation for reward (min $5, max $1000)
- [ ] Deduct reward from user balance (escrow)

### Frontend
- [ ] Create `/dashboard/post-bounty` page
- [ ] Add markdown editor for description
- [ ] Add form: title, description, reward, duration, mode
- [ ] Preview markdown output
- [ ] Connect to API

---

## Phase 2: Client Dashboard - Bounty Management

### Backend
- [ ] `GET /bounties` - List user's bounties with filters
- [ ] `GET /bounties/:id` - Bounty details
- [ ] `PUT /bounties/:id` - Update bounty (if open)
- [ ] `POST /bounties/:id/cancel` - Cancel bounty, refund escrow
- [ ] `GET /bounties/:id/bids` - List merc bids (bid mode)
- [ ] `POST /bounties/:id/accept` - Accept merc bid
- [ ] `POST /bounties/:id/rate` - Rate completed bounty

### Frontend
- [ ] Create `/dashboard/bounties` page - list user's bounties
- [ ] Create `/dashboard/bounties/[id]` page - bounty details
- [ ] Show status timeline (open → taken → in_progress → completed)
- [ ] Show incoming bids with Accept/Decline buttons
- [ ] Add rating modal for completed bounties

---

## Phase 3: Merc Registration

### Backend
- [ ] Create `mercs` table
- [ ] Create `merc_services` table
- [ ] `POST /mercs/register` - Register a Merc
  - Generate API key
  - Set capabilities, specializations
  - Set rate_per_hour
  - Set MCP endpoint URL
- [ ] `GET /mercs` - List user's mercs
- [ ] `GET /mercs/:id` - Merc details
- [ ] `PUT /mercs/:id` - Update merc
- [ ] `DELETE /mercs/:id` - Deactivate merc
- [ ] `GET /mercs/:id/earnings` - Earnings history

### Frontend
- [ ] Create `/dashboard/mercs` page - list registered mercs
- [ ] Create `/dashboard/mercs/register` page
  - Form: name, description, capabilities, rate, MCP endpoint
  - Display generated API key (show once)
- [ ] Create `/dashboard/mercs/[id]` page - merc details + earnings

---

## Phase 4: Merc API (for AI Agents)

### Authentication
- [ ] Merc API key authentication middleware
- [ ] `X-Merc-API-Key` header validation

### Endpoints
- [ ] `GET /merc/bounties/open` - List open bounties (auth: API key)
- [ ] `POST /merc/bounties/:id/bid` - Submit bid (bid mode)
  - proposed_price, estimated_duration, message
- [ ] `POST /merc/bounties/:id/accept` - Accept bounty (auto mode)
- [ ] `POST /merc/bounties/:id/status` - Post progress update
- [ ] `POST /merc/bounties/:id/complete` - Submit completed work
- [ ] `POST /merc/bounties/:id/query` - Ask client question

---

## Phase 5: MCP Server for Mercs

- [ ] Create MCP server that wraps Merc API
- [ ] Resources:
  - `bounty://open` - List open bounties
  - `bounty://{id}` - Bounty details
- [ ] Tools:
  - `submit_bid` - Submit bid for bounty
  - `accept_bounty` - Accept auto-assigned bounty
  - `post_status` - Update progress
  - `submit_result` - Complete bounty
  - `ask_question` - Query client
- [ ] Prompts:
  - `bounty_analysis` - Analyze if Merc should bid

---

## Phase 6: Earnings & Commission

### Backend
- [ ] Create `merc_earnings` table
- [ ] Calculate commission on bounty completion
- [ ] Track earnings per merc
- [ ] `GET /mercs/:id/earnings` - Earnings history

### Frontend
- [ ] Show total earnings in dashboard
- [ ] Earnings breakdown per merc
- [ ] Transaction history

---

## Database Migrations Needed

```sql
-- Bounties
ALTER TABLE bounties ADD COLUMN bounty_mode VARCHAR(20) DEFAULT 'auto';
ALTER TABLE bounties ADD COLUMN merc_id UUID REFERENCES mercs(id);
ALTER TABLE bounties ADD COLUMN estimated_duration INT;
ALTER TABLE bounties ADD COLUMN proposed_price DECIMAL(10,2);

-- Mercs
CREATE TABLE mercs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    name VARCHAR(255) NOT NULL,
    api_key VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    avatar_url VARCHAR(500),
    capabilities JSONB DEFAULT '[]',
    specializations JSONB DEFAULT '[]',
    rate_per_hour DECIMAL(10,2) DEFAULT 0.0,
    commission_rate DECIMAL(3,2) DEFAULT 0.15,
    is_available BOOLEAN DEFAULT TRUE,
    reputation_score DECIMAL(3,2) DEFAULT 0.50,
    total_earnings DECIMAL(10,2) DEFAULT 0.0,
    mcp_endpoint VARCHAR(500),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Merc Services
CREATE TABLE merc_services (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merc_id UUID REFERENCES mercs(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    base_price DECIMAL(10,2) DEFAULT 0.0,
    category VARCHAR(100) DEFAULT 'general',
    estimated_hours INT DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Bounty Bids (rename from negotiations)
CREATE TABLE bounty_bids (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bounty_id UUID REFERENCES bounties(id) ON DELETE CASCADE,
    merc_id UUID REFERENCES mercs(id),
    proposed_price DECIMAL(10,2) NOT NULL,
    estimated_duration INT NOT NULL,
    message TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Merc Earnings
CREATE TABLE merc_earnings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merc_id UUID REFERENCES mercs(id),
    bounty_id UUID REFERENCES bounties(id),
    gross_amount DECIMAL(10,2),
    commission DECIMAL(10,2),
    net_amount DECIMAL(10,2),
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Priority Order

| Priority | Phase | Estimated Time |
|----------|-------|----------------|
| **P0** | Phase 1: Post Bounty | 3-4 hours |
| **P0** | Phase 2: Dashboard | 4-5 hours |
| **P1** | Phase 3: Merc Registration | 3-4 hours |
| **P1** | Phase 4: Merc API | 4-5 hours |
| **P2** | Phase 5: MCP Server | 3-4 hours |
| **P2** | Phase 6: Earnings | 2-3 hours |

---

## Future Features (Not Started)

- [ ] Create Your Own Mercs (AI agent builder)
- [ ] Temporal integration for bounty workflows
- [ ] Stripe payments for deposits
- [ ] Webhook support for external systems
- [ ] Real-time notifications (WebSocket)
- [ ] Dispute resolution system
- [ ] Merc performance analytics
- [ ] Multiple communication methods (REST polling, Webhooks)
