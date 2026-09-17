from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Type

from llm_service import LLMService


class BaseAgent:
    name = 'base_agent'
    soul_file = ''

    def __init__(self, llm: LLMService | None = None):
        self.llm = llm or LLMService()

    def soul(self) -> str:
        path = Path(__file__).parent / 'souls' / self.soul_file
        return path.read_text(encoding='utf-8')

    def try_ai(self, payload: Dict[str, Any], model: Type, fallback):
        response = self.llm.generate_json(self.soul(), payload)
        if response is None:
            return fallback
        try:
            return model.parse_obj(response)
        except Exception as exc:
            print(f'[{self.name}] Invalid model output: {exc}')
            return fallback
