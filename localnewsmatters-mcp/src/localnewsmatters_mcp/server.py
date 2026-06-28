"""MCP server exposing Local News Matters articles and photos.

Run with stdio transport (the default for MCP clients like Claude Desktop / Claude
Code) via the ``localnewsmatters-mcp`` console script or ``python -m
localnewsmatters_mcp.server``.

Interface
---------
Tools (actions over the live catalog):
    * search_articles / get_article / get_article_by_slug
    * list_recent_articles
    * search_photos / get_photo / get_article_photos
    * list_categories / list_tags / list_authors

Resources (read-only data addressable by URI template):
    * lnm://article/{id}        -- a single article as JSON
    * lnm://article/{id}/photos -- photos attached to an article
    * lnm://photo/{id}          -- a single photo's metadata + available sizes
    * lnm://recent/articles     -- the latest published articles
    * lnm://categories          -- the site's sections
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from .wp_client import LocalNewsMattersClient, WordPressError

mcp = FastMCP(
    "localnewsmatters",
    instructions=(
        "Tools and resources for Local News Matters (localnewsmatters.org), a Bay "
        "Area nonprofit local-news publication. Use the tools to search and read "
        "the site's articles and photos. IDs returned by search tools can be fed "
        "into get_article / get_photo or used as resource URIs (lnm://article/{id}, "
        "lnm://photo/{id})."
    ),
)

# A single shared client for the life of the process.
_client = LocalNewsMattersClient()


def _dumps(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


async def _safe(coro) -> Any:
    """Await a client coroutine, converting API errors into a structured result."""
    try:
        return await coro
    except WordPressError as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_articles(
    query: str = "",
    page: int = 1,
    per_page: int = 10,
    category_ids: list[int] | None = None,
    tag_ids: list[int] | None = None,
    author_id: int | None = None,
    after: str | None = None,
    before: str | None = None,
) -> str:
    """Search Local News Matters articles.

    Args:
        query: Full-text search terms. Leave empty to browse the most recent articles.
        page: 1-based page number for paging through results.
        per_page: Results per page (1-100).
        category_ids: Restrict to these category IDs (see list_categories).
        tag_ids: Restrict to these tag IDs (see list_tags).
        author_id: Restrict to a single author (see list_authors).
        after: ISO-8601 date; only articles published on/after it (e.g. "2024-01-01T00:00:00").
        before: ISO-8601 date; only articles published on/before it.

    Returns a JSON object with `results` (article summaries), `total`, `total_pages`, `page`.
    """
    result = await _safe(
        _client.search_articles(
            query=query or None,
            page=page,
            per_page=per_page,
            categories=category_ids,
            tags=tag_ids,
            author=author_id,
            after=after,
            before=before,
        )
    )
    return _dumps(result)


@mcp.tool()
async def list_recent_articles(per_page: int = 10) -> str:
    """List the most recently published Local News Matters articles."""
    result = await _safe(_client.search_articles(per_page=per_page))
    return _dumps(result)


@mcp.tool()
async def get_article(article_id: int) -> str:
    """Fetch a single article by numeric ID, including full body text."""
    return _dumps(await _safe(_client.get_article(article_id)))


@mcp.tool()
async def get_article_by_slug(slug: str) -> str:
    """Fetch a single article by its URL slug (the last path segment of its URL)."""
    result = await _safe(_client.get_article_by_slug(slug))
    if result is None:
        return _dumps({"error": f"No article found with slug '{slug}'."})
    return _dumps(result)


@mcp.tool()
async def search_photos(
    query: str = "",
    page: int = 1,
    per_page: int = 10,
    article_id: int | None = None,
) -> str:
    """Search photos/images in the Local News Matters media library.

    Args:
        query: Search terms matched against title, caption and alt text.
        page: 1-based page number.
        per_page: Results per page (1-100).
        article_id: Restrict to photos attached to a specific article.

    Returns JSON with `results` (photo summaries incl. `source_url`), `total`, `total_pages`.
    """
    result = await _safe(
        _client.search_photos(
            query=query or None,
            page=page,
            per_page=per_page,
            parent_article=article_id,
        )
    )
    return _dumps(result)


@mcp.tool()
async def get_photo(photo_id: int) -> str:
    """Fetch a single photo by numeric ID, including caption, alt text and available sizes."""
    return _dumps(await _safe(_client.get_photo(photo_id)))


@mcp.tool()
async def get_article_photos(article_id: int) -> str:
    """List every photo attached to a given article."""
    return _dumps(await _safe(_client.get_article_photos(article_id)))


@mcp.tool()
async def list_categories() -> str:
    """List the site's categories (sections), ordered by article count."""
    return _dumps(await _safe(_client.list_categories()))


@mcp.tool()
async def list_tags(search: str = "") -> str:
    """List topic tags, optionally filtered by a search term, ordered by usage."""
    return _dumps(await _safe(_client.list_tags(search=search or None)))


@mcp.tool()
async def list_authors() -> str:
    """List the site's authors/contributors."""
    return _dumps(await _safe(_client.list_authors()))


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@mcp.resource(
    "lnm://article/{article_id}",
    name="Article",
    description="A single Local News Matters article (full text) as JSON.",
    mime_type="application/json",
)
async def article_resource(article_id: str) -> str:
    return _dumps(await _safe(_client.get_article(int(article_id))))


@mcp.resource(
    "lnm://article/{article_id}/photos",
    name="Article photos",
    description="Photos attached to a Local News Matters article, as JSON.",
    mime_type="application/json",
)
async def article_photos_resource(article_id: str) -> str:
    return _dumps(await _safe(_client.get_article_photos(int(article_id))))


@mcp.resource(
    "lnm://photo/{photo_id}",
    name="Photo",
    description="A single Local News Matters photo's metadata and available sizes, as JSON.",
    mime_type="application/json",
)
async def photo_resource(photo_id: str) -> str:
    return _dumps(await _safe(_client.get_photo(int(photo_id))))


@mcp.resource(
    "lnm://recent/articles",
    name="Recent articles",
    description="The most recently published Local News Matters articles, as JSON.",
    mime_type="application/json",
)
async def recent_articles_resource() -> str:
    return _dumps(await _safe(_client.search_articles(per_page=20)))


@mcp.resource(
    "lnm://categories",
    name="Categories",
    description="Local News Matters categories (sections), as JSON.",
    mime_type="application/json",
)
async def categories_resource() -> str:
    return _dumps(await _safe(_client.list_categories()))


def main() -> None:
    """Console-script entry point: run the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
