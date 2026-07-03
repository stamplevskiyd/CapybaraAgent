from pydantic_ai.models import Model
from pydantic_ai.models.test import TestModel

from capybara.agent.base import BaseAgent
from capybara.config import Settings


class FakeAgent(BaseAgent):
    def __init__(self, settings: Settings, output_text: str) -> None:
        self._output_text = output_text
        super().__init__(settings)

    def _create_model(self, settings: Settings) -> Model:
        return TestModel(custom_output_text=self._output_text)
