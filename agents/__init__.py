# -*- coding: utf-8 -*-
from agents.react_agent import ReActFlightAgent
from agents.plan_execute_agent import PlanThenExecuteFlightAgent
from agents.hybrid_agent import HybridFlightAgent

AGENT_CLASSES = {
    "ReAct": ReActFlightAgent,
    "Plan-then-Execute": PlanThenExecuteFlightAgent,
    "Lai": HybridFlightAgent,
}


def create_agent(agent_type: str, **kwargs):
    if agent_type not in AGENT_CLASSES:
        raise ValueError(f"Mẫu không hợp lệ: {agent_type}. Chọn: {list(AGENT_CLASSES)}")
    return AGENT_CLASSES[agent_type](**kwargs)


__all__ = ["ReActFlightAgent", "PlanThenExecuteFlightAgent", "HybridFlightAgent", "AGENT_CLASSES", "create_agent"]
