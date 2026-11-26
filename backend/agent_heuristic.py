"""Entry point with the hand-coded rules only:  python evaluate.py --agent agent_heuristic.py

The Stage 5 policy, kept as the safe reference the hybrid is measured against.
"""
from anticipatory.agent import AnticipatoryAgent
from anticipatory.catalog_port import ToolsCatalog


class Agent(AnticipatoryAgent):
    def __init__(self, tools):
        super().__init__(ToolsCatalog(tools))
