"""MediaWiki I/O. Read today; `action=edit` section writes arrive with the publish stage."""

from .client import (
    API_KEY_HEADER,
    MediaWikiReader,
    MediaWikiWriter,
    PageRevision,
    WikiError,
    build_query,
    format_timestamp,
    parse_revision,
    parse_timestamp,
    slug_for,
)
from .diff import SIMILARITY_FLOOR, Row, Segment, counts, diff, to_payload
from .sections import Section, find_section, split_sections, subtree, top_level
from .snapshots import MANIFEST, PageSource, SnapshotPageSource

__all__ = [
    "API_KEY_HEADER",
    "MANIFEST",
    "SIMILARITY_FLOOR",
    "MediaWikiReader",
    "MediaWikiWriter",
    "PageRevision",
    "PageSource",
    "Row",
    "Section",
    "Segment",
    "SnapshotPageSource",
    "WikiError",
    "build_query",
    "counts",
    "diff",
    "find_section",
    "format_timestamp",
    "parse_revision",
    "parse_timestamp",
    "slug_for",
    "split_sections",
    "subtree",
    "to_payload",
    "top_level",
]
