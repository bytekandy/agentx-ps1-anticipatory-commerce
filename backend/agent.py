"""Entry point for the kit's evaluator:  python evaluate.py --agent agent.py

`evaluate.py` builds `Agent(tools)` once and feeds it requests word by word. Everything real
lives in the `anticipatory` package; this file only adapts the harness `tools` to it.
"""
from anticipatory.agent import AnticipatoryAgent
from anticipatory.catalog_port import ToolsCatalog


class Agent(AnticipatoryAgent):
    def __init__(self, tools):
        super().__init__(ToolsCatalog(tools))
