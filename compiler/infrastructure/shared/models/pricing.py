"""Shared model prices and provider usage normalization, in CNY."""

import json
import math
from pathlib import Path

PRICE_TABLE = json.loads(
    Path(__file__).with_name("pricing.json").read_text(encoding="utf-8")
)
MODEL_PRICES = PRICE_TABLE["models"]
TOKEN_UNIT = PRICE_TABLE["unit_tokens"]


def load_prices(path=None):
    source = Path(path).expanduser().resolve() if path else Path(__file__).with_name("pricing.json")
    table = json.loads(source.read_text(encoding="utf-8-sig"))
    if (table.get("currency") != "CNY" or type(table.get("unit_tokens")) is not int
            or table["unit_tokens"] <= 0 or not isinstance(table.get("models"), dict)):
        raise ValueError("Price table requires currency CNY, positive unit_tokens and a models map")
    for price in table["models"].values():
        if not isinstance(price, dict) or any(
                type(rate) not in (int, float) or not math.isfinite(rate) or rate < 0
                for rate in (price.get("input"), price.get("output"), price.get("cached", 0))):
            raise ValueError("Model prices must be finite non-negative input, output and optional cached rates")
    return table, str(source)


def normalize_usage(usage):
    def count(*values):
        for value in values:
            if type(value) is int and value >= 0:
                return value
        return None

    details = (
        usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    )
    output_details = (
        usage.get("completion_tokens_details")
        or usage.get("output_tokens_details")
        or {}
    )
    normalized = {
        "input_tokens": count(usage.get("prompt_tokens"), usage.get("input_tokens")),
        "cached_input_tokens": count(
            details.get("cached_tokens"),
            usage.get("prompt_cache_hit_tokens"),
            usage.get("cached_input_tokens"),
        ),
        "output_tokens": count(
            usage.get("completion_tokens"), usage.get("output_tokens")
        ),
        "reasoning_tokens": count(
            output_details.get("reasoning_tokens"), usage.get("reasoning_tokens")
        ),
        "total_tokens": count(usage.get("total_tokens")),
    }
    if (
        normalized["input_tokens"] is not None
        and normalized["output_tokens"] is not None
    ):
        normalized["total_tokens"] = (
            normalized["input_tokens"] + normalized["output_tokens"]
        )
    return normalized


def estimate_cost(model, usage, prices=None, unit=TOKEN_UNIT):
    price = (MODEL_PRICES if prices is None else prices).get(model)
    if (
        price is None
        or usage.get("input_tokens") is None
        or usage.get("output_tokens") is None
    ):
        return None
    cached = min(usage.get("cached_input_tokens") or 0, usage["input_tokens"])
    return (
        (usage["input_tokens"] - cached) * price["input"]
        + cached * price.get("cached", price["input"])
        + usage["output_tokens"] * price["output"]
    ) / unit
