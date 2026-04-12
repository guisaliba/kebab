from __future__ import annotations

from dataclasses import dataclass

BASE_ALIAS_MAP = {
    "adz": "ads",
    "addz": "ads",
}

KB_DOMAIN_ALIAS_MAPS = {
    "kb_marketing_ptbr_en": {
        "brod": "broad",
        "targetng": "targeting",
        "targting": "targeting",
        "tarjeting": "targeting",
        "metta": "meta",
        "roaz": "roas",
        "baxo": "baixo",
        "diagnostiq": "diagnostico",
    }
}

CORPUS_ALIAS_MAPS = {
    "wiki": {},
    "raw": {},
}


@dataclass
class AliasResolution:
    normalized_tokens: set[str]
    changed_tokens: dict[str, str]


def apply_scoped_aliases(
    tokens: set[str],
    *,
    corpus_type: str,
    domain: str = "kb_marketing_ptbr_en",
    enable_aliases: bool = True,
) -> AliasResolution:
    if not enable_aliases:
        return AliasResolution(normalized_tokens=set(tokens), changed_tokens={})

    base = BASE_ALIAS_MAP
    corpus_map = CORPUS_ALIAS_MAPS.get(corpus_type, {})
    domain_map = KB_DOMAIN_ALIAS_MAPS.get(domain, {})

    # Precedence: domain > corpus > base > original token
    merged = dict(base)
    merged.update(corpus_map)
    merged.update(domain_map)

    normalized_tokens: set[str] = set()
    changed_tokens: dict[str, str] = {}
    for token in tokens:
        normalized = merged.get(token, token)
        normalized_tokens.add(normalized)
        if normalized != token:
            changed_tokens[token] = normalized
    return AliasResolution(normalized_tokens=normalized_tokens, changed_tokens=changed_tokens)
