from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any, Dict, Optional

from src.config import Config

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None


LEXICON_PATH = os.path.join(
    Config.PROJECT_ROOT,
    "frontend",
    "src",
    "data",
    "relationLexicon.json",
)

PUNCTUATION_REGEX = re.compile(r"[\s\u3000·•．。,.，、:：;；!！?？\"'“”‘’()（）\[\]{}<>《》【】\-—_]+")


@lru_cache(maxsize=1)
def load_relation_lexicon() -> Dict[str, Any]:
    with open(LEXICON_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def _get_normalized_prefixes() -> list[str]:
    lexicon = load_relation_lexicon()
    return sorted(
        [(prefix or "").strip().lower() for prefix in lexicon.get("normalizationPrefixes", []) if prefix],
        key=len,
        reverse=True,
    )


@lru_cache(maxsize=1)
def _get_normalized_self_references() -> set[str]:
    lexicon = load_relation_lexicon()
    return {
        normalize_relation_signal(reference)
        for reference in lexicon.get("selfReferences", [])
        if normalize_relation_signal(reference)
    }


@lru_cache(maxsize=1)
def _get_relation_entries() -> list[Dict[str, Any]]:
    lexicon = load_relation_lexicon()
    entries: list[Dict[str, Any]] = []
    for relation_code, meta in lexicon.get("relations", {}).items():
        aliases = [
            normalize_relation_signal(alias)
            for alias in meta.get("aliases", [])
            if normalize_relation_signal(alias)
        ]
        aliases.sort(key=len, reverse=True)
        compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in meta.get("patterns", [])]
        entries.append(
            {
                "code": relation_code,
                "label": meta.get("label", relation_code),
                "group": meta.get("group", "other"),
                "aliases": aliases,
                "patterns": compiled_patterns,
            }
        )
    return entries


@lru_cache(maxsize=1)
def _get_group_patterns() -> dict[str, list[re.Pattern[str]]]:
    lexicon = load_relation_lexicon()
    compiled: dict[str, list[re.Pattern[str]]] = {}
    for group, patterns in lexicon.get("groupPatterns", {}).items():
        compiled[group] = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    return compiled


def normalize_relation_signal(value: str) -> str:
    normalized = (value or "").strip().lower()
    if not normalized:
        return ""

    normalized = PUNCTUATION_REGEX.sub("", normalized)
    for prefix in _get_normalized_prefixes():
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
            break
    return normalized


def is_self_reference(value: str) -> bool:
    return normalize_relation_signal(value) in _get_normalized_self_references()


def _lookup_relation_from_rules(raw_value: str) -> Optional[str]:
    normalized = normalize_relation_signal(raw_value)
    if not normalized:
        return None

    for entry in _get_relation_entries():
        if normalized in entry["aliases"]:
            return entry["code"]

    for entry in _get_relation_entries():
        if any(len(alias) >= 2 and alias in normalized for alias in entry["aliases"]):
            return entry["code"]
        if any(pattern.search(raw_value) or pattern.search(normalized) for pattern in entry["patterns"]):
            return entry["code"]

    return None


def infer_relation_code(value: str, enable_llm_fallback: Optional[bool] = None) -> Optional[str]:
    raw_value = (value or "").strip()
    if not raw_value or is_self_reference(raw_value):
        return None

    rule_match = _lookup_relation_from_rules(raw_value)
    if rule_match:
        return rule_match

    should_use_llm = (
        Config.ENABLE_RELATION_LLM_FALLBACK
        if enable_llm_fallback is None
        else enable_llm_fallback
    )
    if should_use_llm:
        return _infer_relation_code_with_llm(raw_value)

    return None


def infer_relation_group(value: str, explicit_relation: Optional[str] = None) -> str:
    relation_code = infer_relation_code(explicit_relation or "", enable_llm_fallback=False)
    if relation_code:
        return get_relation_group(relation_code)

    raw_value = (value or "").strip()
    normalized = normalize_relation_signal(raw_value)
    if not normalized:
        return "other"

    inferred_code = infer_relation_code(raw_value, enable_llm_fallback=False)
    if inferred_code:
        return get_relation_group(inferred_code)

    for group, patterns in _get_group_patterns().items():
        if any(pattern.search(raw_value) or pattern.search(normalized) for pattern in patterns):
            return group

    return "other"


def get_relation_group(code_or_raw: Optional[str]) -> str:
    value = (code_or_raw or "").strip()
    if not value:
        return "other"

    lexicon = load_relation_lexicon()
    relation_meta = lexicon.get("relations", {}).get(value)
    if relation_meta:
        return relation_meta.get("group", "other")

    if value in lexicon.get("groupLabels", {}):
        return value

    inferred_code = _lookup_relation_from_rules(value)
    if inferred_code:
        return lexicon["relations"][inferred_code].get("group", "other")

    return "other"


def get_relation_label(code_or_raw: Optional[str]) -> str:
    value = (code_or_raw or "").strip()
    if not value:
        return "关系待补充"

    lexicon = load_relation_lexicon()
    relation_meta = lexicon.get("relations", {}).get(value)
    if relation_meta:
        return relation_meta.get("label", value)

    if value in lexicon.get("groupLabels", {}):
        return lexicon["groupLabels"][value]

    inferred_code = _lookup_relation_from_rules(value)
    if inferred_code:
        return lexicon["relations"][inferred_code].get("label", value)

    return value


@lru_cache(maxsize=256)
def _infer_relation_code_with_llm(value: str) -> Optional[str]:
    if not OpenAI or not Config.get_api_key():
        return None

    relation_codes = list(load_relation_lexicon().get("relations", {}).keys())
    prompt = (
        "You are classifying a Chinese interpersonal mention.\n"
        "Return strict JSON with one key: relation_code.\n"
        f"Allowed relation_code values: {', '.join(relation_codes)}, other.\n"
        "Choose the closest kinship/friend/work relation if the mention strongly implies one.\n"
        "If unclear, return other.\n"
        f"Mention: {value}"
    )

    try:
        client = OpenAI(**Config.get_openai_client_kwargs())
        response = client.chat.completions.create(
            model=Config.RELATION_LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": "You classify relation mentions into a fixed schema."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=80,
        )
        content = (response.choices[0].message.content or "").strip()
        if not content:
            return None
        parsed = json.loads(content)
        relation_code = (parsed.get("relation_code") or "").strip()
        if relation_code in load_relation_lexicon().get("relations", {}):
            return relation_code
        return None
    except Exception:
        return None
