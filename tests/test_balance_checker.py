import pytest
from unittest.mock import patch, MagicMock
import os

# Set environment variables for testing before other imports
os.environ['GOOGLE_API_KEY'] = 'test_google_key'
os.environ['OPENAI_API_KEY'] = 'test_openai_key'
os.environ['ANTHROPIC_API_KEY'] = 'test_anthropic_key'

from src.utils.balance_checker import BalanceChecker
from src.analyzer.agent import AnalyzerAgent, TaskRequirement

@pytest.fixture
def mock_profiles():
    """Provides a standard set of model profiles for testing."""
    return {
        'models': [
            {'id': 'gemini-flash', 'provider': 'google', 'reasoning_capability': 'medium', 'context_window': 8000, 'cost_per_1k_tokens': 0.01},
            {'id': 'gpt-4o', 'provider': 'openai', 'reasoning_capability': 'high', 'context_window': 16000, 'cost_per_1k_tokens': 0.05},
            {'id': 'claude-3-sonnet', 'provider': 'anthropic', 'reasoning_capability': 'high', 'context_window': 32000, 'cost_per_1k_tokens': 0.03}
        ],
        'infrastructure': []
    }

@patch('src.utils.balance_checker.BalanceChecker._get_supported_providers', return_value=["google", "openai", "anthropic"])
def test_balance_checker_all_sufficient(mock_providers, mock_profiles):
    """
    Tests that the analyzer selects the cheapest valid model when all providers have sufficient balance.
    """
    with patch('src.analyzer.agent.get_provider_balance', side_effect=[10.0, 20.0, 30.0]) as mock_get_balance:
        with patch('builtins.open', new_callable=MagicMock), \
             patch('yaml.safe_load', return_value=mock_profiles):
            agent = AnalyzerAgent(config_path="dummy_path")
            task_req = TaskRequirement(estimated_duration_seconds=60, memory_mb=512, reasoning_complexity="medium", context_length=4000)
            
            selected_model = agent.select_model(task_req)
            
            # Should select gemini-flash as it's the cheapest and meets medium complexity
            assert selected_model['id'] == 'gemini-flash'
            assert mock_get_balance.call_count == 3

@patch('src.utils.balance_checker.BalanceChecker._get_supported_providers', return_value=["google", "openai", "anthropic"])
def test_balance_checker_google_insufficient(mock_providers, mock_profiles):
    """
    Tests that the analyzer skips Google and selects the next cheapest model (Claude)
    when the Google provider has an insufficient balance.
    """
    # Google balance is low (0.5), OpenAI is high (20.0), Anthropic is high (30.0)
    with patch('src.analyzer.agent.get_provider_balance', side_effect=[0.5, 20.0, 30.0]) as mock_get_balance:
        with patch('builtins.open', new_callable=MagicMock), \
             patch('yaml.safe_load', return_value=mock_profiles):
            agent = AnalyzerAgent(config_path="dummy_path")
            task_req = TaskRequirement(estimated_duration_seconds=60, memory_mb=512, reasoning_complexity="high", context_length=8000)

            selected_model = agent.select_model(task_req)

            # GPT-4o and Claude Sonnet are both valid for 'high' complexity.
            # Claude is cheaper, so it should be selected.
            assert selected_model['id'] == 'claude-3-sonnet'
            # The balance check should have occurred for all models
            assert mock_get_balance.call_count == 3

@patch('src.utils.balance_checker.BalanceChecker._get_supported_providers', return_value=["google", "openai", "anthropic"])
def test_fallback_when_all_balances_low(mock_providers, mock_profiles):
    """
    Tests that the system falls back to the most capable model if all financially viable
    models do not meet the task requirements.
    """
    # All balances are critically low
    with patch('src.analyzer.agent.get_provider_balance', side_effect=[0.1, 0.2, 0.3]) as mock_get_balance:
        with patch('builtins.open', new_callable=MagicMock), \
             patch('yaml.safe_load', return_value=mock_profiles):
            agent = AnalyzerAgent(config_path="dummy_path")
            # This task requires 'extreme' complexity, which no model can satisfy
            task_req = TaskRequirement(estimated_duration_seconds=60, memory_mb=512, reasoning_complexity="extreme", context_length=4000)

            selected_model = agent.select_model(task_req)
            
            # Since no model meets the 'extreme' requirement and all have low balance,
            # it should fallback to the most capable model available regardless of balance.
            # In this case, gpt-4o and claude-3-sonnet are the most capable ('high').
            # Since gpt-4o appears first in the sorted list, it will be chosen.
            assert selected_model['id'] == 'gpt-4o'
            assert mock_get_balance.call_count == 3
