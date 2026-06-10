from functools import lru_cache
from autogen_ext.models.openai import OpenAIChatCompletionClient
from ..config import settings


@lru_cache(maxsize=8)
def make_client(max_tokens: int = 800, model: str = "gpt-4o-mini") -> OpenAIChatCompletionClient:
    return OpenAIChatCompletionClient(
        model=model,
        api_key=settings.openai_api_key,
        temperature=0,
        max_tokens=max_tokens,
    )
