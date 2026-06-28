# Local News Matters MCP server

An [MCP](https://modelcontextprotocol.io) server that exposes the articles and
photos of [Local News Matters](https://localnewsmatters.org) — the Bay City News
Foundation's nonprofit local-news site — to MCP-aware clients such as Claude
Desktop and Claude Code.

It is a thin, read-only wrapper over the site's public WordPress REST API
(`/wp-json/wp/v2/`), normalizing the verbose WordPress JSON into compact,
LLM-friendly objects.

## What it provides

### Tools (search / read the live catalog)

| Tool | Description |
| --- | --- |
| `search_articles` | Full-text article search with paging + filters (category, tag, author, date range). |
| `list_recent_articles` | The latest published articles. |
| `get_article` | A single article by numeric ID, including full body text. |
| `get_article_by_slug` | A single article by its URL slug. |
| `search_photos` | Search the photo/media library (images only). |
| `get_photo` | A single photo's metadata + every available size. |
| `get_article_photos` | All photos attached to a given article. |
| `list_categories` | Site sections, ordered by article count. |
| `list_tags` | Topic tags (optionally filtered). |
| `list_authors` | Contributors / authors. |

### Resources (addressable by URI)

| URI | Description |
| --- | --- |
| `lnm://article/{id}` | One article (full text) as JSON. |
| `lnm://article/{id}/photos` | Photos attached to an article. |
| `lnm://photo/{id}` | One photo's metadata and sizes. |
| `lnm://recent/articles` | The latest articles. |
| `lnm://categories` | The site's categories. |

Because the archive holds thousands of items, the full catalog is reached
through the search/list **tools**; **resource templates** address any individual
item once you know its ID.

## Install & run

Requires Python 3.10+.

```bash
# clone the repo
git clone https://github.com/rnakashima1/localnewsmatters-mcp.git
cd localnewsmatters-mcp

# run it (uv installs dependencies on first run)
uv run localnewsmatters-mcp
# or, once installed into an environment
pip install .
localnewsmatters-mcp
```

The server speaks MCP over **stdio**, which is what desktop clients expect.

## Configure a client

### Claude Code

```bash
claude mcp add localnewsmatters -- uv run --directory /absolute/path/to/clone/localnewsmatters-mcp localnewsmatters-mcp
```

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "localnewsmatters": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/clone/localnewsmatters-mcp", "localnewsmatters-mcp"]
    }
  }
}
```

## Configuration (environment variables)

| Variable | Default | Purpose |
| --- | --- | --- |
| `LNM_BASE_URL` | `https://localnewsmatters.org` | Site root; point at a staging mirror if needed. |
| `LNM_USER_AGENT` | `localnewsmatters-mcp/0.1 …` | Outbound `User-Agent` header. |
| `LNM_TIMEOUT` | `30` | Per-request timeout in seconds. |

## Development

```bash
uv sync          # install runtime + dev dependencies
uv run pytest    # run the test suite (fully offline; HTTP is mocked)
```

## Notes & limitations

- This is an **unofficial** client and is not affiliated with or endorsed by
  Local News Matters / Bay City News Foundation. Please respect the site's terms
  of use and use the data responsibly, with attribution.
- The server depends on the WordPress REST API being publicly enabled at
  `/wp-json/wp/v2/`. If the site changes platforms or restricts the API, the
  endpoints in `wp_client.py` will need to be updated.
- All access is read-only.

## License

MIT
