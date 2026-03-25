import os
import json
import logging
from google import genai
from pydantic import BaseModel, Field
from typing import List, Optional

logger = logging.getLogger("TaskAnalyzer")

try:
    from opik import track
    OPIK_AVAILABLE = True
except ImportError:
    OPIK_AVAILABLE = False
    def track(**kwargs):
        def decorator(fn):
            return fn
        return decorator

def _configure_opik():
    try:
        from src.config import load_settings
        load_settings()
    except Exception:
        pass
        
    url_override = os.environ.get("OPIK_URL_OVERRIDE")
    if url_override and OPIK_AVAILABLE:
        try:
            import opik
            opik.configure(use_local=True, url=url_override)
            logger.info(f"[OPIK] Configured for self-hosted at '{url_override}'")
        except Exception as e:
            logger.warning(f"[OPIK] Configuration failed: {e}")

# _configure_opik will be called in __init__

class TaskRequirement(BaseModel):
    estimated_duration_seconds: int
    memory_mb: int
    reasoning_complexity: str = Field(description="low, medium, high, extreme")
    context_length: int
    requires_concurrency: bool = False
    requires_state_suspension: bool = False
    specialization: str = "general"

class AnalyzerResult(BaseModel):
    infrastructure_id: str
    llm_model_id: str
    estimated_cost: float
    infra_details: dict
    model_details: dict
    reason: str
    specialization: str = "general"

class TaskAnalyzer:
    def __init__(self, config_path: str = "config/profiles.yaml"):
        _configure_opik()
        
        # Load from DB
        try:
            from src.config_db import get_loader
            profiles = get_loader().load_namespace("profiles")
            self.models = profiles.get('models', [])
            self.infrastructure = profiles.get('infrastructure', [])
        except Exception as e:
            logger.error(f"Could not load profiles from DB: {e}")
            self.models = []
            self.infrastructure = []
            
        # Initialize Gemini for statement parsing
        api_key = os.environ.get("GOOGLE_API_KEY")
        if api_key:
            self.client = genai.Client(api_key=api_key)
        else:
            self.client = None

    @track(name="parse_statement")
    async def parse_statement(self, statement: str) -> TaskRequirement:
        """
        Returns a default TaskRequirement. Detailed LLM-driven task decomposition
        and specialization assignment are now offloaded to the Execution Plane (Worker).
        """
        # Return default heuristic immediately to keep Genesis as a fast, thin client.
        return TaskRequirement(
            estimated_duration_seconds=60,
            memory_mb=512,
            reasoning_complexity="medium", # Default to medium, Planner node will decide actual needs
            context_length=1000,
            specialization="general" # Worker Planner will override this
        )

    def select_model(self, task: TaskRequirement) -> dict:
        complexity_tiers = {"low": 1, "medium": 2, "high": 3, "extreme": 4}
        req_tier = complexity_tiers.get(task.reasoning_complexity, 1)

        valid_models = []
        for model in self.models:
            # Capability check
            model_tier = complexity_tiers.get(model['reasoning_capability'], 1)
            if model_tier >= req_tier and model['context_window'] >= task.context_length:
                valid_models.append(model)
        
        if not valid_models:
            # Fallback to most capable model if no models meet the criteria
            all_models_sorted = sorted(self.models, key=lambda x: complexity_tiers.get(x['reasoning_capability'], 1), reverse=True)
            if not all_models_sorted:
                raise ValueError("No models are defined in the configuration.")
            return all_models_sorted[0]
            
        # Return cheapest valid model
        return min(valid_models, key=lambda x: x['cost_per_1k_tokens'])

    def select_infrastructure(self, task: TaskRequirement) -> dict:
        valid_infra = []
        task_minutes = task.estimated_duration_seconds / 60.0

        for infra in self.infrastructure:
            # Check hard limits
            if infra['max_duration_minutes'] < task_minutes:
                continue
            if infra['max_memory_mb'] < task.memory_mb:
                continue
            
            # Capability matching
            if task.requires_state_suspension and infra['best_for'] != 'stateful_burst':
                # AWS lambda durable is best for state suspension, but local server with Temporal works too
                if infra['id'] != 'local_server_docker' and (infra['provider'] != 'aws' or 'durable' not in infra['id']):
                    continue
            
            if task.requires_concurrency and infra['best_for'] == 'high_concurrency':
                # Boost priority implicitly by leaving it in list while filtering others?
                pass 
                
            valid_infra.append(infra)

        if not valid_infra:
            raise ValueError("No infrastructure profile meets the task requirements.")

        # Priority: Prefer local server if it meets all criteria
        local = next((i for i in valid_infra if i['id'] == 'local_server_docker'), None)
        if local:
            return local

        # Specific Overrides for Cloud
        if task.requires_concurrency:
            gcp_run = next((i for i in valid_infra if i['id'] == 'gcp_cloud_run_function'), None)
            if gcp_run: return gcp_run
            
        if task.memory_mb > 10240:
             ec2 = next((i for i in valid_infra if i['id'] == 'aws_ec2_spot_t4g'), None)
             if ec2: return ec2

        # Return cheapest valid infrastructure by cost per minute
        return min(valid_infra, key=lambda x: x['cost_per_minute'])

    def analyze(self, task: TaskRequirement) -> AnalyzerResult:
        selected_model = self.select_model(task)
        selected_infra = self.select_infrastructure(task)
        
        # Super rough cost estimation
        infra_cost = (task.estimated_duration_seconds / 60.0) * selected_infra['cost_per_minute']
        model_cost = (task.estimated_duration_seconds) * (selected_model['cost_per_1k_tokens'] / 1000)
        
        return AnalyzerResult(
            infrastructure_id=selected_infra['id'],
            # We now pass the 'reasoning_capability' (tier) instead of a specific model ID.
            # The LiteLLM Router on the worker will then decide which specific model to use.
            llm_model_id=selected_model['reasoning_capability'],
            estimated_cost=infra_cost + model_cost,
            infra_details=selected_infra,
            model_details=selected_model,
            reason=f"Routing to tier '{selected_model['reasoning_capability']}' using infra {selected_infra['id']}.",
            specialization=task.specialization
        )
