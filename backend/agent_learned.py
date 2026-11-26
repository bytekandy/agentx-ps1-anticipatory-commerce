"""Entry point with the learned risk model:  python evaluate.py --agent agent_learned.py

Same agent as `agent.py`, but the commit policy asks the logistic-regression risk model
(`anticipatory/data/risk_model.json`) instead of the hand-coded heuristic. See the Stage 6 notes
in `docs/round1-plan.md` for why `agent.py` stays the default.
"""
from anticipatory.agent import AnticipatoryAgent
from anticipatory.catalog_port import ToolsCatalog
from anticipatory.risk import LearnedRisk


class Agent(AnticipatoryAgent):
    def __init__(self, tools):
        super().__init__(ToolsCatalog(tools), risk_model=LearnedRisk.from_file())
