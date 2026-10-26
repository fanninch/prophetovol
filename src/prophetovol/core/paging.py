"""Paged lists (INT-11): every list returns a page with the total count."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from prophetovol.core.errors import ValidationFailed, ValidationIssue

T = TypeVar("T")

DEFAULT_PAGE_LIMIT = 50
"""Items per page when the caller does not say."""

MAX_PAGE_LIMIT = 500
"""The largest page a caller may ask for."""


class Page(BaseModel, Generic[T]):
    """One page of a list, with the total number of items."""

    items: list[T] = Field(description="The items on this page, in the list's order.")
    total: int = Field(description="The number of items in the whole list.")
    offset: int = Field(description="The index of the first item on this page in the whole list.")
    limit: int = Field(description="The page size that was asked for.")


def check_page(offset: int, limit: int) -> None:
    """Validate paging arguments.

    :param offset: Index of the first item; at least 0.
    :param limit: Page size; from 1 to :data:`MAX_PAGE_LIMIT`.
    :raises ValidationFailed: If either is out of range.
    """
    issues = []
    if offset < 0:
        issues.append(ValidationIssue("offset", "must be 0 or more"))
    if not 1 <= limit <= MAX_PAGE_LIMIT:
        issues.append(ValidationIssue("limit", f"must be from 1 to {MAX_PAGE_LIMIT}"))
    if issues:
        raise ValidationFailed(issues)
