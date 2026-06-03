from functools import lru_cache
from autogen_ext.models.openai import OpenAIChatCompletionClient
from ..config import settings


@lru_cache(maxsize=8)
def make_client(max_tokens: int = 800, provider: str = "openai") -> object:
    """
    provider: "openai" (gpt-4o-mini) | "claude-haiku" | "claude-sonnet"
    """
    if provider == "claude-haiku":
        from autogen_ext.models.anthropic import AnthropicChatCompletionClient
        return AnthropicChatCompletionClient(
            model="claude-haiku-4-5-20251001",
            api_key=settings.anthropic_api_key,
            max_tokens=max_tokens,
        )
    if provider == "claude-sonnet":
        from autogen_ext.models.anthropic import AnthropicChatCompletionClient
        return AnthropicChatCompletionClient(
            model="claude-sonnet-4-6",
            api_key=settings.anthropic_api_key,
            max_tokens=max_tokens,
        )
    # 기본: OpenAI gpt-4o-mini
    return OpenAIChatCompletionClient(
        model="gpt-4o-mini",
        api_key=settings.openai_api_key,
        temperature=0,
        max_tokens=max_tokens,
    )
