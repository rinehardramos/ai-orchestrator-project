"""
Agent-task matching algorithm.
Calculates attractiveness score and finds best agent for bounty.
"""

from typing import Optional, List, Tuple
from src.mercenary.models import Bounty, Agent
from src.mercenary.db import AgentRepository


class BountyMatcher:
    """
    Match bounties to the best available agent based on:
    1. Price weight (40%) - higher price = more attractive
    2. Skill match (25%) - agent skill vs task difficulty
    3. Duration fit (20%) - reasonable deadline
    4. Agent reputation (15%) - reliability factor
    """
    
    DIFFICULTY_SCORES = {
        'easy': 0.3,
        'medium': 0.5,
        'hard': 0.7,
        'expert': 0.9
    }
    
    SPECIALIZATION_LEVELS = {
        'coding': 0.7,
        'research': 0.5,
        'writing': 0.4,
        'general': 0.5,
        'expert': 0.9
    }
    
    CLAIM_THRESHOLD = 0.6
    
    def calculate_attractiveness(self, bounty: Bounty, agent: Agent) -> float:
        """Calculate how attractive a bounty is to an agent."""
        
        price_score = min(bounty.price / 100, 5.0) / 5.0
        
        hours = bounty.duration_minutes / 60
        if 1 <= hours <= 4:
            duration_score = 1.0
        elif hours < 1:
            duration_score = 0.7
        else:
            duration_score = max(0.3, 1.0 - (hours - 4) * 0.1)
        
        agent_skill = self.SPECIALIZATION_LEVELS.get(agent.specialization, 0.5)
        task_difficulty = self.DIFFICULTY_SCORES.get(bounty.difficulty, 0.5)
        
        if agent.specialization == bounty.specialization:
            skill_score = 1.0
        else:
            skill_score = 1.0 - abs(agent_skill - task_difficulty)
        
        reputation_score = agent.reputation_score
        
        total = (
            price_score * 0.40 +
            duration_score * 0.20 +
            skill_score * 0.25 +
            reputation_score * 0.15
        )
        
        return total
    
    def find_best_agent(self, bounty: Bounty) -> Tuple[Optional[Agent], float]:
        """Find the best available agent for a bounty."""
        repo = AgentRepository()
        agents = repo.get_all(available_only=True)
        
        if not agents:
            return None, 0.0
        
        scores = []
        for agent in agents:
            score = self.calculate_attractiveness(bounty, agent)
            scores.append((agent, score))
        
        scores.sort(key=lambda x: x[1], reverse=True)
        
        best_agent, best_score = scores[0]
        
        if best_score >= self.CLAIM_THRESHOLD:
            return best_agent, best_score
        
        return None, best_score
    
    def estimate_difficulty(self, description: str) -> str:
        """Estimate task difficulty from description."""
        description_lower = description.lower()
        
        expert_keywords = ['architect', 'redesign', 'migrate', 'optimize', 'security audit']
        hard_keywords = ['implement', 'integrate', 'refactor', 'api', 'database']
        easy_keywords = ['write', 'create', 'document', 'summarize', 'format', 'convert']
        
        for keyword in expert_keywords:
            if keyword in description_lower:
                return 'expert'
        
        for keyword in hard_keywords:
            if keyword in description_lower:
                return 'hard'
        
        for keyword in easy_keywords:
            if keyword in description_lower:
                return 'easy'
        
        return 'medium'
