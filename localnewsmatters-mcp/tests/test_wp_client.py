"""Unit tests for the WordPress client and normalization helpers.

HTTP is mocked with respx so the tests are fully offline and deterministic.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from localnewsmatters_mcp.wp_client import (
    LocalNewsMattersClient,
    WordPressError,
    strip_html,
    summarize_article,
    summarize_photo,
)

API = "https://localnewsmatters.org/wp-json/wp/v2"


def _post(**overrides):
    post = {
        "id": 101,
        "slug": "city-council-approves-budget",
        "link": "https://localnewsmatters.org/2024/01/02/city-council-approves-budget/",
        "date": "2024-01-02T08:00:00",
        "title": {"rendered": "City Council Approves &#8216;Budget&#8217;"},
        "excerpt": {"rendered": "<p>A short summary.</p>"},
        "content": {"rendered": "<p>First paragraph.</p><p>Second paragraph.</p>"},
        "categories": [5],
        "tags": [9],
        "_embedded": {
            "author": [{"name": "Jane Reporter"}],
            "wp:featuredmedia": [
                {
                    "id": 555,
                    "source_url": "https://localnewsmatters.org/img/hero.jpg",
                    "mime_type": "image/jpeg",
                    "title": {"rendered": "Hero"},
                    "alt_text": "city hall",
                    "caption": {"rendered": "<p>City hall.</p>"},
                    "media_details": {"width": 1200, "height": 800},
                    "post": 101,
                }
            ],
            "wp:term": [
                [{"taxonomy": "category", "name": "Government"}],
                [{"taxonomy": "post_tag", "name": "Budget"}],
            ],
        },
    }
    post.update(overrides)
    return post


def _media(**overrides):
    media = {
        "id": 555,
        "title": {"rendered": "Hero shot"},
        "alt_text": "city hall exterior",
        "caption": {"rendered": "<p>The city hall.</p>"},
        "source_url": "https://localnewsmatters.org/img/hero.jpg",
        "mime_type": "image/jpeg",
        "link": "https://localnewsmatters.org/hero/",
        "post": 101,
        "media_details": {
            "width": 1200,
            "height": 800,
            "sizes": {
                "thumbnail": {
                    "width": 150,
                    "height": 150,
                    "source_url": "https://localnewsmatters.org/img/hero-150.jpg",
                }
            },
        },
    }
    media.update(overrides)
    return media


def test_strip_html_unescapes_and_flattens():
    assert strip_html("<p>Hello &amp; welcome</p><p>line two</p>") == "Hello & welcome\nline two"
    assert strip_html(None) == ""


def test_summarize_article_normalizes_fields():
    summary = summarize_article(_post())
    assert summary["id"] == 101
    assert summary["uri"] == "lnm://article/101"
    assert summary["title"] == "City Council Approves ‘Budget’"
    assert summary["author"] == "Jane Reporter"
    assert summary["categories"] == ["Government"]
    assert summary["tags"] == ["Budget"]
    assert summary["featured_photo"]["source_url"].endswith("hero.jpg")


def test_summarize_photo_pulls_dimensions():
    photo = summarize_photo(_media())
    assert photo["uri"] == "lnm://photo/555"
    assert photo["width"] == 1200
    assert photo["article_id"] == 101
    assert photo["caption"] == "The city hall."


@respx.mock
async def test_search_articles_parses_results_and_pagination():
    route = respx.get(f"{API}/posts").mock(
        return_value=httpx.Response(
            200,
            json=[_post()],
            headers={"X-WP-Total": "42", "X-WP-TotalPages": "5"},
        )
    )
    async with LocalNewsMattersClient() as client:
        result = await client.search_articles(query="budget", per_page=10)

    assert route.called
    request = route.calls.last.request
    assert request.url.params["search"] == "budget"
    assert request.url.params["_embed"] == "author,wp:featuredmedia,wp:term"
    assert result["total"] == 42
    assert result["total_pages"] == 5
    assert result["results"][0]["title"].startswith("City Council")


@respx.mock
async def test_get_article_includes_content():
    respx.get(f"{API}/posts/101").mock(return_value=httpx.Response(200, json=_post()))
    async with LocalNewsMattersClient() as client:
        article = await client.get_article(101)
    assert article["content"] == "First paragraph.\nSecond paragraph."
    assert article["category_ids"] == [5]


@respx.mock
async def test_get_article_by_slug_returns_none_when_empty():
    respx.get(f"{API}/posts").mock(return_value=httpx.Response(200, json=[]))
    async with LocalNewsMattersClient() as client:
        assert await client.get_article_by_slug("missing") is None


@respx.mock
async def test_search_photos_forces_image_media_type():
    route = respx.get(f"{API}/media").mock(
        return_value=httpx.Response(200, json=[_media()], headers={"X-WP-Total": "1"})
    )
    async with LocalNewsMattersClient() as client:
        result = await client.search_photos(query="city hall")

    assert route.calls.last.request.url.params["media_type"] == "image"
    assert result["results"][0]["source_url"].endswith("hero.jpg")


@respx.mock
async def test_get_photo_includes_sizes():
    respx.get(f"{API}/media/555").mock(return_value=httpx.Response(200, json=_media()))
    async with LocalNewsMattersClient() as client:
        photo = await client.get_photo(555)
    assert "thumbnail" in photo["sizes"]
    assert photo["sizes"]["thumbnail"]["width"] == 150


@respx.mock
async def test_http_error_raises_wordpress_error():
    respx.get(f"{API}/posts/999").mock(
        return_value=httpx.Response(404, json={"message": "Not found", "code": "rest_post_invalid_id"})
    )
    async with LocalNewsMattersClient() as client:
        with pytest.raises(WordPressError) as exc:
            await client.get_article(999)
    assert "404" in str(exc.value)


@respx.mock
async def test_network_failure_raises_wordpress_error():
    respx.get(f"{API}/posts").mock(side_effect=httpx.ConnectError("boom"))
    async with LocalNewsMattersClient() as client:
        with pytest.raises(WordPressError):
            await client.search_articles()


def test_base_url_override_via_env(monkeypatch):
    monkeypatch.setenv("LNM_BASE_URL", "https://staging.example.org/")
    client = LocalNewsMattersClient()
    assert client.api_root == "https://staging.example.org/wp-json/wp/v2"
