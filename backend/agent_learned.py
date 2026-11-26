"""Entry point with the learned risk model:  python evaluate.py --agent agent_learned.py

Same agent as `agent.py`, but the commit policy asks the logistic-regression risk model
(`anticipatory/data/risk_model.json`) alone, without the hand-coded rules for fresh values.
It scores higher on dev but makes wrong commits on corrections; see `docs/round1-plan.md`.
"""
from anticipatory.agent import AnticipatoryAgent
from anticipatory.catalog_port import ToolsCatalog
from anticipatory.risk import LearnedRisk


class Agent(AnticipatoryAgent):
    def __init__(self, tools):
        super().__init__(ToolsCatalog(tools), risk_model=LearnedRisk.from_file())
