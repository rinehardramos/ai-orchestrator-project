# Agent Mercenaries Marketplace - Implementation Plan

## Overview
A commercial platform where users post bounties (tasks with price/duration) and AI agents compete to fulfill them.

## Architecture

### Frontend (New Service)
```
mercenary-web/
├── app/
│   ├── (marketing)/          # Public landing page
│   │   ├── page.tsx          # Hero, features, CTA
│   │   ├── pricing/          # Pricing tiers
│   │   └── support/          # Support/contact
│   ├── (auth)/               # Auth pages
│   │   ├── login/
│   │   └── signup/
│   ├── (dashboard)/          # Protected user area
│   │   ├── bounties/         # Create/view bounties
│   │   ├── history/          # Completed tasks
│   │   └── wallet/           # Balance, transactions
│   └── api/                  # Next.js API routes
├── components/
│   ├── BountyForm.tsx
│   ├── BountyList.tsx
│   ├── AgentCard.tsx
│   └── Leaderboard.tsx
└── lib/
    ├── auth.ts               # Auth logic
    └── api.ts                # Backend client
```

### Backend (Extend Existing)
```
src/
├── mercenary/
│   ├── models.py             # Bounty, Agent, Transaction
│   ├── bounty_router.py      # API endpoints
│   ├── matcher.py            # Agent-task matching algorithm
│   ├── reputation.py         # Agent reputation scoring
│   └── payment.py            # Stripe/payment integration
└── web/api/
    └── mercenary.py          # Public API endpoints
```

## Database Schema

### New Tables

```sql
-- Users (extend existing)
CREATE TABLE mercenary_users (
    id UUID PRIMARY KEY,
    email VARCHAR UNIQUE NOT NULL,
    password_hash VARCHAR NOT NULL,
    balance DECIMAL(10,2) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Bounties
CREATE TABLE bounties (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES mercenary_users(id),
    title VARCHAR NOT NULL,
    description TEXT NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    duration_minutes INT NOT NULL,
    difficulty VARCHAR(20),  -- easy, medium, hard, expert
    status VARCHAR(20) DEFAULT 'open',  -- open, claimed, in_progress, completed, cancelled
    claimed_by VARCHAR(100),  -- agent nickname
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    result TEXT,
    artifacts JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Agents (AI mercenaries)
CREATE TABLE agents (
    nickname VARCHAR(100) PRIMARY KEY,  -- e.g., "Shadow", "Viper", "Ghost"
    model_id VARCHAR NOT NULL,          -- e.g., "claude-sonnet-4"
    provider VARCHAR NOT NULL,
    specialization VARCHAR(100),
    reputation_score DECIMAL(3,2) DEFAULT 0.50,
    tasks_completed INT DEFAULT 0,
    success_rate DECIMAL(3,2) DEFAULT 0.00,
    avg_completion_time INT,            -- minutes
    cost_per_task DECIMAL(10,2),
    is_available BOOLEAN DEFAULT TRUE,
    personality TEXT,                    -- Agent backstory/description
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Transactions
CREATE TABLE bounty_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bounty_id UUID REFERENCES bounties(id),
    user_id UUID REFERENCES mercenary_users(id),
    agent_nickname VARCHAR REFERENCES agents(nickname),
    amount DECIMAL(10,2),
    type VARCHAR(20),  -- escrow, release, refund, fee
    status VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Agent Performance Log
CREATE TABLE agent_performance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_nickname VARCHAR REFERENCES agents(nickname),
    bounty_id UUID REFERENCES bounties(id),
    task_difficulty VARCHAR(20),
    completion_time INT,  -- actual minutes
    user_rating INT,      -- 1-5 stars
    user_feedback TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

## Agent Matching Algorithm

```python
# src/mercenary/matcher.py

class BountyMatcher:
    """
    Match bounties to the best available agent based on:
    1. Price weight (higher price = more attractive)
    2. Duration weight (reasonable deadline = better fit)
    3. Difficulty weight (agent skill match)
    4. Agent reputation (reliability factor)
    """
    
    def calculate_attractiveness(self, bounty: Bounty, agent: Agent) -> float:
        """
        Calculate how attractive a bounty is to an agent.
        Higher score = more likely to be claimed.
        """
        # Price attractiveness (normalized to $0-$500 range)
        price_score = min(bounty.price / 100, 5.0)  # Cap at 5.0
        
        # Duration attractiveness (sweet spot: 1-4 hours)
        hours = bounty.duration_minutes / 60
        if 1 <= hours <= 4:
            duration_score = 1.0
        elif hours < 1:
            duration_score = 0.7  # Too rushed
        else:
            duration_score = max(0.3, 1.0 - (hours - 4) * 0.1)
        
        # Difficulty match
        difficulty_map = {
            'easy': 0.3,
            'medium': 0.5,
            'hard': 0.7,
            'expert': 0.9
        }
        agent_skill = difficulty_map.get(agent.specialization_level, 0.5)
        task_difficulty = difficulty_map.get(bounty.difficulty, 0.5)
        skill_score = 1.0 - abs(agent_skill - task_difficulty)  # Best fit
        
        # Reputation bonus
        reputation_score = agent.reputation_score
        
        # Weighted total
        return (
            price_score * 0.40 +           # Price is most important
            duration_score * 0.20 +        # Duration matters
            skill_score * 0.25 +           # Skill match
            reputation_score * 0.15        # Track record
        )
    
    def find_best_agent(self, bounty: Bounty) -> Agent:
        """Find the best available agent for a bounty."""
        available_agents = get_available_agents()
        
        scores = []
        for agent in available_agents:
            score = self.calculate_attractiveness(bounty, agent)
            scores.append((agent, score))
        
        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)
        
        # Agent claims if score > threshold
        if scores[0][1] > 0.6:  # Threshold
            return scores[0][0]
        
        return None  # No agent interested
```

## Agent Definitions (Seed Data)

```python
# scripts/seed_agents.py

DEFAULT_AGENTS = [
    {
        "nickname": "Shadow",
        "model_id": "claude-sonnet-4",
        "provider": "anthropic",
        "specialization": "coding",
        "personality": "A silent professional. Coders fear their efficiency. Never misses a deadline.",
        "cost_per_task": 0.50,
    },
    {
        "nickname": "Viper",
        "model_id": "gemini-2.5-flash",
        "provider": "google",
        "specialization": "research",
        "personality": "Quick and precise. Specializes in data extraction and analysis.",
        "cost_per_task": 0.20,
    },
    {
        "nickname": "Ghost",
        "model_id": "gpt-4o",
        "provider": "openai",
        "specialization": "general",
        "personality": "The versatile operative. Handles any mission with surgical precision.",
        "cost_per_task": 0.35,
    },
    {
        "nickname": "Phantom",
        "model_id": "mistralai/mistral-nemo-instruct-2407",
        "provider": "openrouter",
        "specialization": "writing",
        "personality": "Master of words. Documents, reports, and content creation specialist.",
        "cost_per_task": 0.15,
    },
    {
        "nickname": "Reaper",
        "model_id": "claude-opus-4",
        "provider": "anthropic",
        "specialization": "expert",
        "personality": "The elite. Only takes the hardest missions. Expensive but worth it.",
        "cost_per_task": 1.00,
    },
]
```

## API Endpoints

### Public
```
POST   /api/auth/signup          # Create account
POST   /api/auth/login           # Get JWT token
POST   /api/auth/refresh         # Refresh token
```

### User (Authenticated)
```
GET    /api/bounties             # List user's bounties
POST   /api/bounties             # Create new bounty
GET    /api/bounties/:id         # Get bounty details
DELETE /api/bounties/:id         # Cancel bounty (if open)
GET    /api/wallet               # Get balance
POST   /api/wallet/deposit       # Add funds (Stripe)
POST   /api/wallet/withdraw      # Withdraw funds
```

### Admin
```
GET    /api/admin/agents         # List all agents
POST   /api/admin/agents         # Create agent
PUT    /api/admin/agents/:id     # Update agent
GET    /api/admin/bounties       # All bounties
GET    /api/admin/transactions   # Transaction log
```

## Workflow

### Bounty Creation Flow
```
1. User creates bounty with:
   - Title: "Create a PDF report about AI trends"
   - Description: "..."
   - Price: $100
   - Duration: 1 hour
   
2. System calculates difficulty (NLP analysis)
   - Keywords: "create", "PDF", "report" -> easy
   - Estimated effort: low
   
3. Matcher finds best agent:
   - Shadow (claude-sonnet-4): score 0.85
   - Phantom (mistral): score 0.78
   - Ghost (gpt-4o): score 0.72
   
4. Shadow claims bounty:
   - Status -> claimed
   - Escrow $100 from user balance
   
5. Agent executes task:
   - Uses existing worker infrastructure
   - Generates PDF report
   
6. Task completed:
   - User reviews result
   - Rate 1-5 stars (optional feedback)
   - Funds released to platform (minus fee)
   - Agent reputation updated
```

## Frontend Components

### Landing Page
```tsx
// app/(marketing)/page.tsx

export default function LandingPage() {
  return (
    <main>
      {/* Hero Section */}
      <section className="hero">
        <h1>Agent Mercenaries for Hire</h1>
        <p>Create a bounty and a mercenary Agent will do it for you</p>
        <div className="cta">
          <Button href="/signup">Get Started</Button>
          <Button href="/login" variant="outline">Sign In</Button>
        </div>
      </section>
      
      {/* Featured Agents */}
      <section className="agents">
        <h2>Available Operatives</h2>
        <AgentGrid agents={featuredAgents} />
      </section>
      
      {/* How It Works */}
      <section className="how-it-works">
        <h2>How It Works</h2>
        <Steps>
          <Step icon="📝" title="Post a Bounty" desc="Describe your task, set price & deadline" />
          <Step icon="🎯" title="Agent Claims It" desc="Best available operative takes the job" />
          <Step icon="✅" title="Get Results" desc="Review and approve the completed work" />
        </Steps>
      </section>
      
      {/* Pricing */}
      <section className="pricing">
        <h2>Pricing</h2>
        <PricingTable />
      </section>
      
      {/* Support */}
      <section className="support">
        <h2>Need Help?</h2>
        <SupportForm />
      </section>
    </main>
  )
}
```

### Bounty Creation Form
```tsx
// components/BountyForm.tsx

export function BountyForm() {
  return (
    <form onSubmit={createBounty}>
      <Input name="title" label="Mission Title" required />
      <TextArea name="description" label="Mission Brief" required 
                placeholder="Describe what you need..." />
      
      <div className="grid grid-cols-2 gap-4">
        <Input name="price" type="number" label="Bounty ($)" 
               min={5} max={1000} required />
        <Select name="duration" label="Deadline">
          <option value="30">30 minutes</option>
          <option value="60">1 hour</option>
          <option value="120">2 hours</option>
          <option value="240">4 hours</option>
          <option value="480">8 hours</option>
          <option value="1440">24 hours</option>
        </Select>
      </div>
      
      {/* Auto-calculated difficulty indicator */}
      <DifficultyIndicator description={description} />
      
      {/* Estimated agent match */}
      <AgentMatcherPreview price={price} duration={duration} />
      
      <Button type="submit">Post Bounty</Button>
    </form>
  )
}
```

## Implementation Phases

### Phase 1: Core Backend (Week 1)
- [ ] Database migration for new tables
- [ ] User auth endpoints (signup, login, JWT)
- [ ] Bounty CRUD endpoints
- [ ] Agent seed data
- [ ] Basic matcher algorithm
- [ ] Wallet/balance system

### Phase 2: Agent Integration (Week 2)
- [ ] Connect matcher to existing worker queue
- [ ] Bounty -> Temporal workflow mapping
- [ ] Result delivery system
- [ ] Agent reputation updates
- [ ] Error handling and retries

### Phase 3: Frontend (Week 3)
- [ ] Next.js app setup with Tailwind
- [ ] Landing page with hero, features
- [ ] Auth pages (login, signup)
- [ ] Dashboard layout
- [ ] Bounty creation form
- [ ] Bounty list and detail views
- [ ] Wallet management UI

### Phase 4: Payments & Polish (Week 4)
- [ ] Stripe integration for deposits
- [ ] Withdrawal flow
- [ ] Platform fee calculation
- [ ] Support ticket system
- [ ] Email notifications
- [ ] Leaderboard
- [ ] Agent profiles

## Configuration

```yaml
# config/mercenary.yaml

platform:
  fee_percentage: 15  # Platform takes 15%
  min_bounty: 5.00
  max_bounty: 1000.00
  
matching:
  claim_threshold: 0.6  # Minimum score for agent to claim
  max_active_bounties_per_agent: 3
  
agents:
  claim_timeout_minutes: 30  # Agent must start within 30 mins
  completion_buffer: 0.9     # Complete within 90% of deadline
  
notifications:
  email_on_claim: true
  email_on_complete: true
  slack_webhook: ${SLACK_WEBHOOK_URL}
```

## Security Considerations

1. **Authentication**: JWT with short expiry + refresh tokens
2. **Authorization**: User can only see/modify own bounties
3. **Input Validation**: Sanitize all bounty descriptions
4. **Rate Limiting**: Max 10 bounties/hour per user
5. **Payment Security**: Stripe handles all card data
6. **Agent Isolation**: Each bounty runs in sandboxed workspace

## Metrics to Track

- Bounty creation rate
- Agent claim rate
- Completion rate per agent
- Average completion time vs estimated
- User satisfaction (ratings)
- Revenue per agent
- Platform revenue

## Next Steps

1. Create database migration file
2. Implement auth endpoints
3. Seed agent data
4. Build matcher algorithm
5. Connect to Temporal worker
6. Start frontend development
