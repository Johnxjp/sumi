"""OpenRouter client and structured-output call used to generate eval queries."""

from openrouter import OpenRouter
from openrouter.components import (
    ChatFormatJSONSchemaConfig,
    ChatJSONSchemaConfig,
    ChatSystemMessage,
    ChatUserMessage,
)
from openrouter.utils import BackoffStrategy, RetryConfig
from pydantic import BaseModel

from evals.config import settings

client = OpenRouter(
    api_key=settings.api_key,
    retry_config=RetryConfig(
        "backoff",
        BackoffStrategy(
            initial_interval=1_000,
            max_interval=60_000,
            exponent=2,
            max_elapsed_time=300_000,
        ),
        retry_connection_errors=True,
        # SDK default only retries 5XX; 429 must be opted into explicitly.
        status_codes_override=["429", "5XX"],
    ),
)


def _strict_schema(response_schema: type[BaseModel]) -> dict:
    """Strict mode rejects any object that doesn't set additionalProperties=False."""
    schema = response_schema.model_json_schema()
    for obj in [schema, *schema.get("$defs", {}).values()]:
        obj["additionalProperties"] = False
    return schema


async def generate_queries(
    system_prompt: str,
    user_prompt: str,
    response_schema: type[BaseModel] | None = None,
    temperature: float = 0.0,
    model: str = settings.model_name,
) -> BaseModel:
    """Call OpenRouter and parse the response into `response_schema`."""

    response_format = (
        ChatFormatJSONSchemaConfig(
            type="json_schema",
            json_schema=ChatJSONSchemaConfig(
                name=response_schema.__name__,
                schema=_strict_schema(response_schema),
                strict=True,
            ),
        )
        if response_schema
        else None
    )

    result = await client.chat.send_async(
        model=model,
        messages=[
            ChatSystemMessage(role="system", content=system_prompt),
            ChatUserMessage(role="user", content=user_prompt),
        ],
        temperature=temperature,
        response_format=response_format,
    )

    if response_schema is None:
        return result.choices[0].message.content
    return response_schema.model_validate_json(result.choices[0].message.content)
