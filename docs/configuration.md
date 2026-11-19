# Configuration

Detailed configuration for server permissions, tool filtering, and authentication.

## Outbound Cookie Header

Set `OUTLINE_COOKIE` on the MCP server to include an additional `Cookie`
header when it calls the Outline API. This is useful when a self-hosted
instance sits behind a gateway that requires a cookie. It works with all
MCP transports (`stdio`, `sse`, and `streamable-http`).

```bash
export OUTLINE_API_KEY="your-outline-api-key"
export OUTLINE_API_URL="https://outline.example.com/api"
export OUTLINE_COOKIE="session=your_session; gateway=your_gateway_token"
uv run mcp-outline
```

Use the complete header value without the `Cookie:` prefix. Multiple
cookies are separated by `; `. Unset or empty values omit the configured
cookie. Surrounding whitespace and wrapping quotes are removed; control
characters and non-ASCII values are rejected without logging the value.

The existing `Authorization: Bearer ...` header is still sent, so an Outline
API key is still required. This is a server-wide configuration shared by
users of that deployment, not a forwarded cookie from incoming MCP requests.

The configured cookie is kept on redirects within the same origin (scheme,
host, and port), and is removed when redirects lead elsewhere, including
attachment storage. It is not added to the shared HTTP client's cookie jar.

For Docker, pass `-e OUTLINE_COOKIE="session=your_session"` or use
`--env-file`. The repository's Docker Compose service also reads
`OUTLINE_COOKIE` from the shell or project `.env` file. Rebuild and recreate
the MCP service after updating the source or environment:

```bash
docker compose up -d --build mcp-outline
```

## Read-Only Mode

Set `OUTLINE_READ_ONLY=true` to enable viewer-only access. Only search, read, export, and collaboration viewing tools are available. All write operations (create, update, move, archive, delete) are disabled.

**Use cases:**
- Shared access for team members who should only view content
- Safe integration with AI assistants that should not modify documents
- Public or demo instances where content should be protected

**Available tools in read-only mode:**
- Search & Discovery: `search_documents`, `list_collections`, `get_collection_structure`, `get_document_id_from_title`
- Document Reading: `read_document`, `export_document`
- Attachments: `list_document_attachments`, `get_attachment_url`, `fetch_attachment`
- Comments: `list_document_comments`, `get_comment`
- Collaboration: `get_document_backlinks`
- Collections: `export_collection`, `export_all_collections`
- AI: `ask_ai_about_documents` (if not disabled with `OUTLINE_DISABLE_AI_TOOLS`)

## Disable Delete Operations

Set `OUTLINE_DISABLE_DELETE=true` to allow create and update workflows while preventing accidental data loss. Only delete operations are disabled.

**Use cases:**
- Production environments where documents should not be deleted
- Protecting against accidental deletions
- Safe content editing workflows

**Disabled tools:**
- `delete_document`, `delete_collection`
- `batch_delete_documents`

**Important:** `OUTLINE_READ_ONLY=true` takes precedence over `OUTLINE_DISABLE_DELETE`. If both are set, the server operates in read-only mode.

## Disable Recent-Changes Tool

Set `OUTLINE_DISABLE_RECENT_DOCUMENTS=true` to hide the `list_recently_updated_documents` tool. Only this tool is disabled.

**Use cases:**
- Trimming the tool list when a recent-changes view isn't needed
- Deployments that prefer `search_documents` as the only discovery path

**Disabled tools:**
- `list_recently_updated_documents`

## Multi-User Setup (HTTP)

When running in HTTP mode (`sse` or `streamable-http`), multiple users can share a single MCP server, each authenticating with their own Outline API key.

### Per-User Outline API Keys

Each user passes their own Outline API key via the `x-outline-api-key` HTTP header instead of (or in addition to) the `OUTLINE_API_KEY` environment variable.

**Priority:** Header value takes precedence over the environment variable. If the header is not present, the server falls back to the env var.

**Example** (with a streamable-http server on port 3000):

Start the server:

```bash
docker run -p 3000:3000 \
  -e OUTLINE_API_KEY=<DEFAULT_KEY> \
  -e MCP_TRANSPORT=streamable-http \
  ghcr.io/vortiago/mcp-outline:latest
```

Then connect from your client with a user-specific key:

**VS Code** (`.vscode/mcp.json`):
```json
{
  "servers": {
    "mcp-outline": {
      "type": "http",
      "url": "http://localhost:3000/mcp",
      "headers": {
        "x-outline-api-key": "<YOUR_KEY>"
      }
    }
  }
}
```

**Claude Code** (`.mcp.json`):
```json
{
  "mcpServers": {
    "mcp-outline": {
      "type": "http",
      "url": "http://localhost:3000/mcp",
      "headers": {
        "x-outline-api-key": "<YOUR_KEY>"
      }
    }
  }
}
```

> **Note:** The `x-outline-api-key` header is only available for HTTP transports (SSE, streamable-http). In `stdio` mode, you must set `OUTLINE_API_KEY` via environment variable or a [dotenv config file](client-setup.md#claude-code-plugin). If it is missing, the server still starts but every tool call will return an error with setup instructions.

### Dynamic Tool List

Set `OUTLINE_DYNAMIC_TOOL_LIST=true` to automatically filter the tool list based on each user's Outline role and API key scopes. This pairs well with per-user Outline API keys — each user sees only the tools their key allows.

**How it works:**

On each `tools/list` request, the server performs two independent checks:

1. **Role check** (`auth.info`) — tools requiring a higher role than the user's are hidden (e.g. viewers cannot see member/admin tools)
2. **Scope check** (`apiKeys.list`) — if the API key has restricted scopes, tools for excluded endpoints are hidden. See the [Outline API documentation](https://www.getoutline.com/developers) for details on scope formats and available scopes.

Both results are combined. Each check fails open independently — if either call fails (e.g. the key lacks `apiKeys.list` scope), that check is skipped and all tools remain visible. There are two exceptions: a **401** from `apiKeys.list` (invalid/expired key) and **key not found by last4** (key deleted or mismatched) — in both cases, all tools are hidden.

> **Note:** This is a convenience feature, not a security boundary. Even if a tool is hidden from the list, Outline's own API enforces permissions on individual operations.

This feature composes with `OUTLINE_READ_ONLY` and `OUTLINE_DISABLE_DELETE`. If `OUTLINE_READ_ONLY=true`, write tools are never registered regardless of this setting.

For architecture details and diagrams, see [Dynamic Tool List Architecture](dynamic-tool-list.md).
