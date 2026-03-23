import os
import sys
import pytest

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from src.genesis.analyzer.task_analyzer import TaskAnalyzer, TaskRequirement

@pytest.fixture
def analyzer():
    # Make sure we use the absolute path to the config
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../config/profiles.yaml'))
    return TaskAnalyzer(config_path=config_path)

def test_light_task(analyzer):
    # With local_pi/local_server_docker removed, it should select the next cheapest (AWS Lambda or GCP Cloud Run)
    analyzer.infrastructure = [i for i in analyzer.infrastructure if i['provider'] not in ['local_network', 'existing_infra']]
    task = TaskRequirement(
        estimated_duration_seconds=5,
        memory_mb=128,
        reasoning_complexity="low",
        context_length=500
    )
    result = analyzer.analyze(task)
    # With local_pi removed, it should select the next cheapest (AWS Lambda or GCP Cloud Run)
    assert result.infrastructure_id in ["aws_lambda_durable", "gcp_cloud_run_function"]
    # Now it returns the tier (reasoning_capability)
    assert result.llm_model_id == "low"

def test_heavy_reasoning_task(analyzer):
    analyzer.infrastructure = [i for i in analyzer.infrastructure if i['provider'] not in ['local_network', 'existing_infra']]
    task = TaskRequirement(
        estimated_duration_seconds=600,
        memory_mb=4096,
        reasoning_complexity="high", # extreme not in profiles.yaml as a capability
        context_length=100000
    )
    result = analyzer.analyze(task)
    # Now it returns the tier (reasoning_capability)
    assert result.llm_model_id == "high"
    assert result.infrastructure_id == "aws_lambda_durable"

def test_heavy_local_task(analyzer):
    task = TaskRequirement(
        estimated_duration_seconds=3600, # 1 hour
        memory_mb=32768, # 32GB
        reasoning_complexity="medium",
        context_length=10000
    )
    result = analyzer.analyze(task)
    # 32GB is too much for Lambda, and local_server_docker is cheaper (free) than EC2
    assert result.infrastructure_id == "local_server_docker"
    assert result.llm_model_id == "medium"
