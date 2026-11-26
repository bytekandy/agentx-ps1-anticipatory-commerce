"""Entry point for the kit's evaluator:  python evaluate.py --agent agent.py

`evaluate.py` builds `Agent(tools)` once and feeds it requests word by word. Everything real
lives in the `anticipatory` package; this file only adapts the harness `tools` to it.

The commit policy asks `HybridRisk`: the hand-coded rules while a value is fresh or just
followed by a pause, the learned model (`anticipatory/data/risk_model.json`) once the state is
calm. `agent_heuristic.py` (rules only) and `agent_learned.py` (model only) are the other two
variants, kept for comparison.
"""
from anticipatory.agent import AnticipatoryAgent
from anticipatory.policy import ToolsCatalog
from anticipatory.risk import HybridRisk, LearnedRisk


class Agent(AnticipatoryAgent):
    def __init__(self, tools):
        super().__init__(ToolsCatalog(tools), risk_model=HybridRisk(LearnedRisk.from_file()))
