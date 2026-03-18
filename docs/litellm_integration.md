# LiteLLM Integration

## Overview

The AI Orchestration Architecture has been updated to use **LiteLLM** as the unified proxy and gateway for all Large Language Model (LLM) communications across the Execution Plane (and incrementally the Control Plane).

## Motivation

Previously, individual SDKs (`google-genai`, `openai`, `anthropic`) were maintained and invoked conditionally. As the system scaled to support diverse workloads requiring different models (e.g. Gemini 1.5 Pro for multimodal tasks, Claude 3.5 Sonnet for reasoning, GPT-4o for coding), maintaining raw SDK implementations became brittle and complicated the codebase.

LiteLLM provides a standardized interface allowing the system to invoke any provider's model using the exact same code structure, abstracting away API differences.

## Key Changes

1. **Unified Dependencies**: `litellm>=1.0.0` has been added to `requirements.txt` and `requirements.worker.txt`.
2. **Dynamic Generation Wrapper**: The worker node now uses a unified `generate_content` function that dynamically routes requests to the correct provider using LiteLLM's standard `<provider>/<model>` convention.
3. **Provider Normalization**: Google models are mapped to `gemini` under the hood for LiteLLM prefix compatibility.
4. **Model Registry Updates**: `google/gemini-1.5-pro` and other critical models can now be added to the Model Selector service seamlessly without needing to wire up a new client SDK.

## Using LiteLLM in the Architecture

To request a generation via the unified interface:

```python
from src.execution.worker.worker import generate_content

# The wrapper automatically structures the call correctly for LiteLLM
response = generate_content(
    provider="anthropic",
    model="claude-3-opus", 
    prompt="Explain temporal workflows"
)
```

## Future Work

*   Migrate all remaining LLM calls (e.g., in the CNC node's intent parser) to use LiteLLM to reduce binary size and dependencies.
*   Implement cost tracking directly via LiteLLM's `completion_cost` features.
