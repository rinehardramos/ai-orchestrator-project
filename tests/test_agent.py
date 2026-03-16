import os
import sys
import pytest

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from src.analyzer.agent import AnalyzerAgent, TaskRequirement

@pytest.fixture
def agent():
    # Make sure we use the absolute path to the config
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../config/profiles.yaml'))
    return AnalyzerAgent(config_path=config_path)

def test_light_task(agent):
    task = TaskRequirement(
        estimated_duration_seconds=5,
        memory_mb=128,
        reasoning_complexity="low",
        context_length=500
    )
    result = agent.analyze(task)
    # With local_pi removed, it should select the next cheapest (AWS Lambda or GCP Cloud Run)
    assert result.infrastructure_id in ["aws_lambda_durable", "gcp_cloud_run_function"]
    assert result.llm_model_id in ["llama-3.1-8b-local", "gemini-3.1-flash-lite"]

def test_heavy_reasoning_task(agent):
    task = TaskRequirement(
        estimated_duration_seconds=600,
        memory_mb=4096,
        reasoning_complexity="extreme",
        context_length=100000
    )
    result = agent.analyze(task)
    # AWS lambda durable or EC2 might be selected based on cheapest for 10 minutes.
    # Lambda durable (0.000016) vs EC2 (0.00007). Lambda should win.
    assert result.llm_model_id == "gpt-5.4-thinking"
    assert result.infrastructure_id == "aws_lambda_durable"

def test_heavy_local_task(agent):
    task = TaskRequirement(
        estimated_duration_seconds=3600, # 1 hour
        memory_mb=32768, # 32GB
        reasoning_complexity="medium",
        context_length=10000
    )
    result = agent.analyze(task)
    # 32GB is too much for Lambda, and local_server_docker is cheaper (free) than EC2
    assert result.infrastructure_id == "local_server_docker"
    assert result.llm_model_id == "gemini-3.1-flash"
