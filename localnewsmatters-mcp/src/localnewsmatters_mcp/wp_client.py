"""Thin async client over the WordPress REST API used by localnewsmatters.org.

Local News Matters (https://localnewsmatters.org) is a WordPress site, so its
content is available through the standard WP REST API at ``/wp-json/wp/v2/``:

* ``posts``      -> articles
* ``media``      -> photos / images
* ``categories`` -> sections
* ``tags``       -> topics
* ``users``      -> authors

This module wraps the handful of endpoints we need and normalizes the verbose
WordPress JSON into compact dictionaries that are pleasant for an LLM to read.
"""

from __future__ import annotations

import html
import os
from html.parser import HTMLParser
from typing import Any, Iterable

import httpx

DEFAULT_BASE_URL = "https://localnewsmatters.org"
DEFAULT_USER_AGENT = "localnewsmatters-mcp/0.1 (+https://localnewsmatters.org)"
DEFAULT_TIMEOUT = 30.0


class _HTMLTextExtractor(HTMLParser):
    """Collapse a fragment of rendered HTML down to readable plain text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("p", "br", "li", "div", "h1", "h2", "h3", "h4", "tr"):
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._parts.append(data)

    def text(self) -> str:
        joined = "".join(self._parts)
        # Collapse runs of whitespace within lines, trim blank lines.
        lines = [" ".join(line.split()) for line in joined.splitlines()]
        cleaned = "\n".join(line for line in lines if line)
        return cleaned.strip()


def strip_html(value: str | None) -> str:
    """Return plain text for a chunk of WordPress ``*.rendered`` HTML."""
    if not value:
        return ""
    parser = _HTMLTextExtractor()
    parser.feed(value)
    parser.close()
    return html.unescape(parser.text())


def _rendered(node: Any) -> str:
    """Pull ``{"rendered": "..."}`` out of a WP field, returning plain text."""
    if isinstance(node, dict):
        return strip_html(node.get("rendered", ""))
    return strip_html(node if isinstance(node, str) else "")


class WordPressError(RuntimeError):
    """Raised when the WordPress REST API returns an error or is unreachable."""


class LocalNewsMattersClient:
    """Async client for the Local News Matters WordPress REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        user_agent: str | None = None,
        timeout: float | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("LNM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.api_root = f"{self.base_url}/wp-json/wp/v2"
        self._user_agent = user_agent or os.environ.get("LNM_USER_AGENT") or DEFAULT_USER_AGENT
        self._timeout = timeout if timeout is not None else float(
            os.environ.get("LNM_TIMEOUT", DEFAULT_TIMEOUT)
        )
        self._external_client = client is not None
        self._client = client

    async def __aenter__(self) -> "LocalNewsMattersClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={"User-Agent": self._user_agent, "Accept": "application/json"},
                timeout=self._timeout,
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._external_client:
            await self._client.aclose()
            self._client = None

    # -- low-level ---------------------------------------------------------

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        client = self._ensure_client()
        url = f"{self.api_root}/{path.lstrip('/')}"
        clean = {k: v for k, v in (params or {}).items() if v not in (None, "", [])}
        try:
            resp = await client.get(url, params=clean)
        except httpx.HTTPError as exc:  # network/timeout failures
            raise WordPressError(f"Request to {url} failed: {exc}") from exc
        if resp.status_code >= 400:
            detail = ""
            try:
                body = resp.json()
                detail = body.get("message") or body.get("code") or ""
            except Exception:
                detail = resp.text[:200]
            raise WordPressError(
                f"WordPress API returned HTTP {resp.status_code} for {url}: {detail}".strip()
            )
        return resp

    @staticmethod
    def _pagination(resp: httpx.Response) -> dict[str, int]:
        def _int(header: str) -> int:
            try:
                return int(resp.headers.get(header, 0))
            except (TypeError, ValueError):
                return 0

        return {"total": _int("X-WP-Total"), "total_pages": _int("X-WP-TotalPages")}

    # -- articles ----------------------------------------------------------

    async def search_articles(
        self,
        query: str | None = None,
        *,
        page: int = 1,
        per_page: int = 10,
        categories: Iterable[int] | None = None,
        tags: Iterable[int] | None = None,
        author: int | None = None,
        after: str | None = None,
        before: str | None = None,
        order: str = "desc",
        orderby: str = "date",
    ) -> dict[str, Any]:
        params = {
            "search": query,
            "page": page,
            "per_page": max(1, min(per_page, 100)),
            "categories": _csv(categories),
            "tags": _csv(tags),
            "author": author,
            "after": after,
            "before": before,
            "order": order,
            "orderby": orderby,
            "_embed": "author,wp:featuredmedia,wp:term",
        }
        resp = await self._get("posts", params)
        items = [summarize_article(post) for post in resp.json()]
        return {"results": items, **self._pagination(resp), "page": page}

    async def get_article(self, article_id: int) -> dict[str, Any]:
        resp = await self._get(
            f"posts/{article_id}", {"_embed": "author,wp:featuredmedia,wp:term"}
        )
        return full_article(resp.json())

    async def get_article_by_slug(self, slug: str) -> dict[str, Any] | None:
        resp = await self._get(
            "posts", {"slug": slug, "_embed": "author,wp:featuredmedia,wp:term"}
        )
        data = resp.json()
        if not data:
            return None
        return full_article(data[0])

    # -- photos / media ----------------------------------------------------

    async def search_photos(
        self,
        query: str | None = None,
        *,
        page: int = 1,
        per_page: int = 10,
        parent_article: int | None = None,
    ) -> dict[str, Any]:
        params = {
            "search": query,
            "page": page,
            "per_page": max(1, min(per_page, 100)),
            "media_type": "image",
            "parent": parent_article,
        }
        resp = await self._get("media", params)
        items = [summarize_photo(m) for m in resp.json()]
        return {"results": items, **self._pagination(resp), "page": page}

    async def get_photo(self, photo_id: int) -> dict[str, Any]:
        resp = await self._get(f"media/{photo_id}")
        return full_photo(resp.json())

    async def get_article_photos(self, article_id: int, *, per_page: int = 50) -> dict[str, Any]:
        resp = await self._get(
            "media",
            {"parent": article_id, "media_type": "image", "per_page": min(per_page, 100)},
        )
        return {"article_id": article_id, "photos": [summarize_photo(m) for m in resp.json()]}

    # -- taxonomy / authors ------------------------------------------------

    async def list_categories(self, *, per_page: int = 100) -> list[dict[str, Any]]:
        resp = await self._get(
            "categories", {"per_page": min(per_page, 100), "orderby": "count", "order": "desc"}
        )
        return [summarize_term(t) for t in resp.json()]

    async def list_tags(self, *, search: str | None = None, per_page: int = 100) -> list[dict[str, Any]]:
        resp = await self._get(
            "tags", {"search": search, "per_page": min(per_page, 100), "orderby": "count", "order": "desc"}
        )
        return [summarize_term(t) for t in resp.json()]

    async def list_authors(self, *, per_page: int = 100) -> list[dict[str, Any]]:
        resp = await self._get("users", {"per_page": min(per_page, 100)})
        return [summarize_author(a) for a in resp.json()]


def _csv(values: Iterable[int] | None) -> str | None:
    if not values:
        return None
    return ",".join(str(v) for v in values)


# -- normalization helpers -------------------------------------------------


def _embedded(post: dict[str, Any]) -> dict[str, Any]:
    return post.get("_embedded", {}) or {}


def _featured_media(post: dict[str, Any]) -> dict[str, Any] | None:
    media = _embedded(post).get("wp:featuredmedia") or []
    if media and isinstance(media[0], dict) and "source_url" in media[0]:
        return summarize_photo(media[0])
    return None


def _author_name(post: dict[str, Any]) -> str | None:
    authors = _embedded(post).get("author") or []
    if authors and isinstance(authors[0], dict):
        return authors[0].get("name")
    return None


def _term_names(post: dict[str, Any]) -> dict[str, list[str]]:
    cats: list[str] = []
    tags: list[str] = []
    for group in _embedded(post).get("wp:term") or []:
        for term in group or []:
            if not isinstance(term, dict):
                continue
            taxonomy = term.get("taxonomy")
            name = term.get("name")
            if not name:
                continue
            if taxonomy == "category":
                cats.append(name)
            elif taxonomy == "post_tag":
                tags.append(name)
    return {"categories": cats, "tags": tags}


def summarize_article(post: dict[str, Any]) -> dict[str, Any]:
    terms = _term_names(post)
    return {
        "id": post.get("id"),
        "uri": f"lnm://article/{post.get('id')}",
        "title": _rendered(post.get("title")),
        "slug": post.get("slug"),
        "url": post.get("link"),
        "date": post.get("date"),
        "excerpt": _rendered(post.get("excerpt")),
        "author": _author_name(post),
        "categories": terms["categories"],
        "tags": terms["tags"],
        "featured_photo": _featured_media(post),
    }


def full_article(post: dict[str, Any]) -> dict[str, Any]:
    summary = summarize_article(post)
    summary["content"] = _rendered(post.get("content"))
    summary["modified"] = post.get("modified")
    summary["category_ids"] = post.get("categories", [])
    summary["tag_ids"] = post.get("tags", [])
    return summary


def summarize_photo(media: dict[str, Any]) -> dict[str, Any]:
    details = media.get("media_details", {}) or {}
    return {
        "id": media.get("id"),
        "uri": f"lnm://photo/{media.get('id')}",
        "title": _rendered(media.get("title")),
        "alt_text": media.get("alt_text", ""),
        "caption": _rendered(media.get("caption")),
        "source_url": media.get("source_url"),
        "mime_type": media.get("mime_type"),
        "width": details.get("width"),
        "height": details.get("height"),
        "article_id": media.get("post"),
        "page_url": media.get("link"),
    }


def full_photo(media: dict[str, Any]) -> dict[str, Any]:
    photo = summarize_photo(media)
    details = media.get("media_details", {}) or {}
    sizes = details.get("sizes", {}) or {}
    photo["date"] = media.get("date")
    photo["sizes"] = {
        name: {
            "width": size.get("width"),
            "height": size.get("height"),
            "source_url": size.get("source_url"),
        }
        for name, size in sizes.items()
        if isinstance(size, dict)
    }
    return photo


def summarize_term(term: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": term.get("id"),
        "name": term.get("name"),
        "slug": term.get("slug"),
        "count": term.get("count"),
        "description": strip_html(term.get("description", "")),
        "url": term.get("link"),
    }


def summarize_author(author: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": author.get("id"),
        "name": author.get("name"),
        "slug": author.get("slug"),
        "description": strip_html(author.get("description", "")),
        "url": author.get("link"),
    }
