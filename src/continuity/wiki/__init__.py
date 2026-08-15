"""MediaWiki I/O. Read today; `action=edit` section writes arrive with the publish stage."""

from .client import (
    MCU_WIKI_API,
    USER_AGENT,
    MediaWikiReader,
    PageRevision,
    WikiError,
    build_query,
    parse_revision,
    parse_timestamp,
    slug_for,
)

__all__ = [
    "MCU_WIKI_API",
    "USER_AGENT",
    "MediaWikiReader",
    "PageRevision",
    "WikiError",
    "build_query",
    "parse_revision",
    "parse_timestamp",
    "slug_for",
]
