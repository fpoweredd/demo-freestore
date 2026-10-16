"""Search and tag helpers for product cards (SQLite + PostgreSQL friendly)."""

from __future__ import annotations

import re

from django.db.models import Q


def normalize_csv_field(value: str | None) -> str:
    parts = [x.strip() for x in (value or "").split(",") if x.strip()]
    return ", ".join(parts)


def tokenize_search(raw: str) -> list[str]:
    s = (raw or "").strip()
    if not s:
        return []
    parts = re.split(r"[\s,;]+", s)
    return [p.strip() for p in parts if p.strip()][:32]


def build_card_search_q(tokens: list[str]) -> Q | None:
    """Each token must match at least one of: name, description, public_tags, search_hints."""
    if not tokens:
        return None
    combined = Q()
    for t in tokens:
        term_q = (
            Q(name__icontains=t)
            | Q(description__icontains=t)
            | Q(public_tags__icontains=t)
            | Q(search_hints__icontains=t)
        )
        combined &= term_q
    return combined


def filter_cards_by_public_tag(queryset, tag: str):
    """Cards whose normalized comma-separated public_tags contain this tag (whole segment)."""
    tag = (tag or "").strip().lower()
    if not tag:
        return queryset
    return queryset.filter(_public_tag_match_q(tag))


def _public_tag_match_q(tag_lower: str) -> Q:
    sep = ", "
    return (
        Q(public_tags__iexact=tag_lower)
        | Q(public_tags__istartswith=f"{tag_lower}{sep}")
        | Q(public_tags__iendswith=f"{sep}{tag_lower}")
        | Q(public_tags__icontains=f"{sep}{tag_lower}{sep}")
    )
