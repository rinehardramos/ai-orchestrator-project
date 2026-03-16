from typing import TypedDict, Annotated, List, Union
from langgraph.graph import StateGraph, END

class AgentState(TypedDict):
    task: str
    infra_choice: str
    model_choice: str
    status: str
    history: List[str]

# Node 1: Analyze Node (Uses Gemini)
def analyze_node(state: AgentState):
    print(f"🔍 [LangGraph] Analyzing task: {state['task']}")
    # Call Gemini (as we did in AnalyzerAgent)
    # For now, return a placeholder decision
    return {"infra_choice": "local_server_docker" if "local" in state['task'].lower() else "aws_ec2_spot_t4g",
            "model_choice": "gemini-3.1-flash",
            "status": "ready_to_provision"}

# Node 2: Provision Node
def provision_node(state: AgentState):
    print(f"🚀 [LangGraph] Triggering Provisioning for {state['infra_choice']}")
    # This is where we call the Temporal Activity that runs Pulumi
    return {"status": "provisioned"}

# Define the Graph
workflow = StateGraph(AgentState)
workflow.add_node("analyze", analyze_node)
workflow.add_node("provision", provision_node)

workflow.set_entry_point("analyze")
workflow.add_edge("analyze", "provision")
workflow.add_edge("provision", END)

# Compile
app = workflow.compile()
