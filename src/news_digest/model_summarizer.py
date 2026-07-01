"""Opt-in, evidence-bound model synthesis with synchronous cost ceilings."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Mapping, Protocol, Sequence
from urllib.request import Request, urlopen

from .models import DigestItem, EventCluster
from .summarize import deterministic_fallback, parse_synthesis, synthesis_prompt


class ModelBudgetExceeded(RuntimeError):
    """Raised before network I/O when an estimated hard ceiling would be crossed."""


@dataclass(frozen=True)
class ModelPrice:
    input_per_million_usd: Decimal
    output_per_million_usd: Decimal


@dataclass(frozen=True)
class ModelRequest:
    model: str
    prompt: str
    max_output_tokens: int


class StructuredModelClient(Protocol):
    def complete_json(self, request: ModelRequest) -> str: ...


class OpenAIResponsesClient:
    """Minimal Responses API client; API keys are sent only in Authorization."""

    endpoint = "https://api.openai.com/v1/responses"

    def __init__(self, api_key: str, timeout_seconds: int = 30) -> None:
        if not api_key:
            raise ValueError("model API key is required")
        self._api_key = api_key
        self._timeout = timeout_seconds

    def complete_json(self, request: ModelRequest) -> str:
        schema = {
            "type": "object", "additionalProperties": False,
            "required": ["headline", "clauses"],
            "properties": {
                "headline": {"type": "string"},
                "clauses": {"type": "array", "minItems": 1, "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["text", "evidence_ids", "analysis"],
                    "properties": {"text": {"type": "string"},
                                   "evidence_ids": {"type": "array", "minItems": 1,
                                                    "items": {"type": "string"}},
                                   "analysis": {"type": "boolean"}}}},
            },
        }
        body = json.dumps({
            "model": request.model, "input": request.prompt,
            "max_output_tokens": request.max_output_tokens,
            "text": {"format": {"type": "json_schema", "name": "grounded_digest",
                                "strict": True, "schema": schema}},
        }, ensure_ascii=False).encode()
        http_request = Request(self.endpoint, data=body, method="POST",
                               headers={"Authorization": "Bearer " + self._api_key,
                                        "Content-Type": "application/json"})
        with urlopen(http_request, timeout=self._timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        for output in payload.get("output", []):
            for content in output.get("content", []):
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    return str(content["text"])
        raise ValueError("model response did not contain structured output text")


def estimated_tokens(text: str) -> int:
    """Conservative local estimate used only to reject work before a request."""
    return max(1, math.ceil(len(text.encode("utf-8")) / 3))


class BudgetedModelSummarizer:
    def __init__(self, client: StructuredModelClient, prices: Mapping[str, ModelPrice],
                 nano_model: str, mini_model: str, max_run_usd: Decimal = Decimal("0.10"),
                 max_request_usd: Decimal = Decimal("0.03"), max_output_tokens: int = 500,
                 mini_router: Callable[[EventCluster], bool] | None = None) -> None:
        self.client, self.prices = client, dict(prices)
        self.nano_model, self.mini_model = nano_model, mini_model
        self.max_run_usd, self.max_request_usd = max_run_usd, max_request_usd
        self.max_output_tokens = max_output_tokens
        self.mini_router = mini_router or (lambda cluster: cluster.investment_relevance)

    def _request(self, cluster: EventCluster) -> ModelRequest:
        return ModelRequest(self.mini_model if self.mini_router(cluster) else self.nano_model,
                            synthesis_prompt(cluster), self.max_output_tokens)

    def estimate(self, request: ModelRequest) -> Decimal:
        price = self.prices.get(request.model)
        if price is None:
            raise ModelBudgetExceeded("no explicit price configured for model: " + request.model)
        input_cost = Decimal(estimated_tokens(request.prompt)) * price.input_per_million_usd
        output_cost = Decimal(request.max_output_tokens) * price.output_per_million_usd
        return (input_cost + output_cost) / Decimal(1_000_000)

    def summarize_all(self, clusters: Sequence[EventCluster]) -> list[DigestItem]:
        requests = [self._request(cluster) for cluster in clusters]
        estimates = [self.estimate(request) for request in requests]
        if any(cost > self.max_request_usd for cost in estimates):
            raise ModelBudgetExceeded("estimated model request exceeds configured ceiling")
        if sum(estimates, Decimal("0")) > self.max_run_usd:
            raise ModelBudgetExceeded("estimated model run exceeds $%.2f ceiling" % self.max_run_usd)
        results: list[DigestItem] = []
        for cluster, request in zip(clusters, requests):
            try:
                results.append(parse_synthesis(cluster, self.client.complete_json(request)))
            except (OSError, ValueError, TypeError, KeyError):
                # Availability or malformed output must not weaken evidence validation.
                results.append(deterministic_fallback(cluster))
        return results


def prices_from_json(raw: str) -> Mapping[str, ModelPrice]:
    data = json.loads(raw)
    if not isinstance(data, dict) or not data:
        raise ValueError("MODEL_PRICING_JSON must be a non-empty object")
    result = {}
    for model, value in data.items():
        if not isinstance(value, dict):
            raise ValueError("each model price must be an object")
        result[str(model)] = ModelPrice(Decimal(str(value["input_per_million_usd"])),
                                        Decimal(str(value["output_per_million_usd"])))
    return result
