"""Unit tests for inbox conversation fuzzy search helpers."""

from __future__ import annotations

from app.services.conversations import _escape_like, _normalize_phone_digits, _search_filter


def test_normalize_phone_digits() -> None:
    assert _normalize_phone_digits("0812-3456-7890") == "081234567890"
    assert _normalize_phone_digits("+62 812 3456") == "628123456"
    assert _normalize_phone_digits("  08 12  ") == "0812"


def test_escape_like() -> None:
    assert _escape_like("a%b_c") == "a\\%b\\_c"


def test_search_filter_empty() -> None:
    assert _search_filter("") is None
    assert _search_filter("   ") is None


def test_search_filter_builds_clause() -> None:
    clause = _search_filter("LLK-MRNCC")
    assert clause is not None
    sql = str(clause)
    assert "customer_email" in sql or "lower" in sql.lower()
