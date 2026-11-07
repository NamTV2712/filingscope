"""Gold-answer numeric metrics for the P5 offline evaluation boundary."""

from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal
from typing import Any

from src.decision.period_value_parser import extract_period_value_mentions


_CITATION_RE = re.compile(r"[\[【][^\]】]*[\]】]")
_TEXT_TOKEN_RE = re.compile(r"[a-z]+|\d+(?:[.,]\d+)?%?")
_SCALE_FACTORS = {
    "unit": Decimal("1"),
    "thousand": Decimal("1000"),
    "million": Decimal("1000000"),
    "billion": Decimal("1000000000"),
}


def _signature(mention: Any) -> tuple[str, str | None, str, str | None, str | None]:
    pair = mention.pair
    value = Decimal(pair.numeric_value)
    scale = pair.scale or ("unit" if pair.value_kind == "percent" else None)
    if scale in _SCALE_FACTORS:
        value *= _SCALE_FACTORS[scale]
        normalized_value = format(value.normalize(), "f")
        normalized_scale = "base"
    else:
        normalized_value = format(value.normalize(), "f")
        normalized_scale = scale
    period = re.sub(r"\s+", "", pair.period.casefold()) if pair.period else None
    return pair.value_kind, pair.currency, normalized_value, normalized_scale, period


def numeric_fact_signatures(
    answer: str,
) -> tuple[tuple[str, str | None, str, str | None, str | None], ...]:
    """Extract value claims while excluding citation labels and bare years."""
    clean = _CITATION_RE.sub(lambda match: " " * len(match.group(0)), answer)
    return tuple(_signature(mention) for mention in extract_period_value_mentions(clean))


def _numeric_true_positives(
    predicted: Counter[tuple[str, str | None, str, str | None, str | None]],
    gold: Counter[tuple[str, str | None, str, str | None, str | None]],
) -> int:
    remaining = predicted.copy()
    matched = 0
    # Consume period-specific labels first; an unlabelled gold fact can match
    # an answer fact with an explicit period, but cannot mask an available
    # period-specific gold fact with the same value.
    for signature in sorted(gold, key=lambda item: item[4] is None):
        count = gold[signature]
        direct = min(count, remaining[signature])
        matched += direct
        remaining[signature] -= direct
        unmatched = count - direct
        if unmatched and signature[4] is None:
            for candidate in tuple(remaining):
                if candidate[:4] != signature[:4] or candidate[4] is None:
                    continue
                used = min(unmatched, remaining[candidate])
                matched += used
                unmatched -= used
                remaining[candidate] -= used
                if unmatched == 0:
                    break
    return matched


def score_numeric_answer(prediction: str, gold_answer: str) -> dict[str, Any]:
    """Score exact numeric fact equality; return None when the gold has no numbers."""
    predicted = Counter(numeric_fact_signatures(prediction))
    gold = Counter(numeric_fact_signatures(gold_answer))
    if not gold:
        return {
            "scored": False,
            "exact_match": None,
            "true_positive_count": 0,
            "predicted_numeric_count": sum(predicted.values()),
            "gold_numeric_count": 0,
            "precision": None,
            "recall": None,
            "f1": None,
        }
    true_positive = _numeric_true_positives(predicted, gold)
    predicted_count = sum(predicted.values())
    gold_count = sum(gold.values())
    precision = true_positive / predicted_count if predicted_count else 0.0
    recall = true_positive / gold_count if gold_count else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "scored": True,
        "exact_match": predicted_count == gold_count == true_positive,
        "true_positive_count": true_positive,
        "predicted_numeric_count": predicted_count,
        "gold_numeric_count": gold_count,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def score_text_answer(prediction: str, gold_answer: str) -> dict[str, Any]:
    """Return normalized exact match and token overlap as lexical QA metrics."""
    predicted_sequence = tuple(_TEXT_TOKEN_RE.findall(_CITATION_RE.sub(" ", prediction).casefold()))
    gold_sequence = tuple(_TEXT_TOKEN_RE.findall(_CITATION_RE.sub(" ", gold_answer).casefold()))
    predicted_tokens = Counter(predicted_sequence)
    gold_tokens = Counter(gold_sequence)
    predicted_count = sum(predicted_tokens.values())
    gold_count = sum(gold_tokens.values())
    true_positive = sum((predicted_tokens & gold_tokens).values())
    precision = true_positive / predicted_count if predicted_count else 0.0
    recall = true_positive / gold_count if gold_count else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "scored": bool(gold_count),
        "exact_match": predicted_sequence == gold_sequence,
        "true_positive_token_count": true_positive,
        "predicted_token_count": predicted_count,
        "gold_token_count": gold_count,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }
