from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Type

from llm_service import LLMService


class BaseAgent:
    name: str = 'base_agent'
    soul_file: str = ''

    def __init__(self, llm: LLMService | None = None):
        self.llm = llm or LLMService()

    def soul(self) -> str:
        """Load system prompt from OpenClaw workspace directory (SOUL.md + AGENTS.md) with fallback."""
        agent_dir = Path(__file__).parent / self.name
        if agent_dir.exists() and agent_dir.is_dir():
            soul_path = agent_dir / 'SOUL.md'
            agents_path = agent_dir / 'AGENTS.md'
            parts = []
            if soul_path.exists():
                parts.append(soul_path.read_text(encoding='utf-8').strip())
            if agents_path.exists():
                parts.append(agents_path.read_text(encoding='utf-8').strip())
            if parts:
                return "\n\n---\n\n".join(parts)

        # Fallback to legacy souls/ directory
        if self.soul_file:
            path = Path(__file__).parent / 'souls' / self.soul_file
            if path.exists():
                return path.read_text(encoding='utf-8')
        return ''

    def try_ai(self, payload: Dict[str, Any], model: Type, fallback):
        system_prompt = self.soul()
        response = self.llm.generate_json(system_prompt, payload)
        if response is None or not isinstance(response, dict):
            return fallback

        try:
            if hasattr(model, 'model_validate'):
                return model.model_validate(response)
            elif hasattr(model, 'parse_obj'):
                return model.parse_obj(response)
            return model(**response)
        except Exception as exc:
            print(f"[{self.name}] Invalid structured output from AI: {exc}. Using deterministic fallback.")
            return fallback
