"""
Document attachment tools for the MCP Outline server.

This module provides MCP tools for fetching and discovering attachments
(PDFs, images, etc.) in Outline documents.
"""

import base64
import mimetypes
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from mcp.types import ToolAnnotations

from mcp_outline.features.documents.common import (
    OutlineClientError,
    get_outline_client,
)

# Pattern for /api/attachments.redirect?id=<uuid>
ATTACHMENT_PATTERN = re.compile(
    r"/api/attachments\.redirect\?id="
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)

_CONTENT_TYPE_OVERRIDES = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
}


def _guess_content_type(filename: str) -> str:
    """Guess a file's MIME type with stable common text mappings."""
    suffix = Path(filename).suffix.lower()
    return (
        _CONTENT_TYPE_OVERRIDES.get(suffix)
        or mimetypes.guess_type(filename)[0]
        or "application/octet-stream"
    )


def _parse_attachment_ids(text: str) -> List[Tuple[str, str]]:
    """Extract attachment IDs and context from document text.

    Args:
        text: The document text (markdown/content) to parse.

    Returns:
        List of (attachment_id, context_snippet) tuples.
    """
    results: List[Tuple[str, str]] = []
    seen: set[str] = set()

    for match in ATTACHMENT_PATTERN.finditer(text):
        attachment_id = match.group(1)
        if attachment_id in seen:
            continue
        seen.add(attachment_id)

        start = max(0, match.start() - 40)
        end = min(len(text), match.end() + 40)
        snippet = text[start:end].replace("\n", " ").strip()
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        results.append((attachment_id, snippet))

    return results


def _format_attachment_list(
    document_title: str, attachments: List[Tuple[str, str]]
) -> str:
    """Format attachment list for display."""
    if not attachments:
        return f"Document '{document_title}': No attachments found."

    lines = [
        f"Document '{document_title}': {len(attachments)} attachment(s)\n"
    ]
    for i, (aid, snippet) in enumerate(attachments, 1):
        lines.append(f"{i}. ID: {aid}")
        lines.append(f"   Context: {snippet}\n")
    return "\n".join(lines).rstrip()


def register_tools(mcp) -> None:
    """
    Register document attachment tools with the MCP server.

    Args:
        mcp: The MCPServer server instance
    """

    @mcp.tool(
        annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
        meta={
            "endpoint": "attachments.redirect",
            "min_role": "viewer",
        },
    )
    async def get_attachment_url(attachment_id: str) -> str:
        """
        Resolve an attachment ID to a downloadable URL.

        Calls attachments.redirect and returns the final URL after the
        redirect. Allows clients/agents to fetch the file themselves.

        Use this tool when you need to:
        - Get a direct URL to download an attachment
        - Share or reference an attachment URL
        - Let another system fetch the file

        Args:
            attachment_id: The attachment UUID

        Returns:
            The redirect URL (signed download URL)
        """
        try:
            client = await get_outline_client()
            url = await client.get_attachment_redirect_url(attachment_id)
            return url
        except OutlineClientError as e:
            return f"Error: {str(e)}"
        except Exception as e:
            return f"Unexpected error: {str(e)}"

    @mcp.tool(
        annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
        meta={
            "endpoint": "attachments.redirect",
            "min_role": "viewer",
        },
    )
    async def fetch_attachment(attachment_id: str) -> str:
        """
        Fetch attachment content and return it as base64.

        Calls attachments.redirect, follows the redirect, and returns the
        raw file content encoded as base64. Useful for images and files
        that agents can process.

        Use this tool when you need to:
        - Read PDF content from Outline documents
        - Process embedded images
        - Analyze files referenced in documents
        - Enable AI tools to work with all document content

        Args:
            attachment_id: The attachment UUID

        Returns:
            Multi-line string in this format (blank line after Content-Length
            / before Content-Base64):
            Content-Type: <mime-type>
            Content-Length: <bytes>

            Content-Base64: <base64-encoded-data>

            Note: For large files (e.g. multi-MB PDFs), the base64 output
            may hit token limits. Prefer get_attachment_url to obtain a
            download URL for large attachments, then fetch externally.
        """
        try:
            client = await get_outline_client()
            content, content_type = await client.fetch_attachment_content(
                attachment_id
            )
            b64 = base64.b64encode(content).decode("ascii")
            return (
                f"Content-Type: {content_type}\n"
                f"Content-Length: {len(content)}\n\n"
                f"Content-Base64: {b64}"
            )
        except OutlineClientError as e:
            return f"Error: {str(e)}"
        except Exception as e:
            return f"Unexpected error: {str(e)}"

    @mcp.tool(
        annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
        meta={
            "endpoint": "documents.info",
            "min_role": "viewer",
        },
    )
    async def list_document_attachments(document_id: str) -> str:
        """
        List attachment IDs referenced in a document.

        Parses document content for attachment references (e.g.
        /api/attachments.redirect?id=<uuid>) and returns a list of
        attachment IDs with context snippets.

        Use this tool when you need to:
        - Discover attachments within a document
        - Find attachment IDs for use with get_attachment_url or
          fetch_attachment
        - Audit what files a document references

        Args:
            document_id: The document ID to scan

        Returns:
            Formatted list of attachment IDs and context
        """
        try:
            client = await get_outline_client()
            document = await client.get_document(document_id)
            title = document.get("title", "Untitled Document")
            text = document.get("text", "")
            attachments = _parse_attachment_ids(text)
            return _format_attachment_list(title, attachments)
        except OutlineClientError as e:
            return f"Error: {str(e)}"
        except Exception as e:
            return f"Unexpected error: {str(e)}"

    read_only = os.getenv("OUTLINE_READ_ONLY", "").lower() in (
        "true",
        "1",
        "yes",
    )

    if not read_only:

        @mcp.tool(
            annotations=ToolAnnotations(
                read_only_hint=False,
                destructive_hint=False,
                idempotent_hint=False,
            ),
            meta={
                "endpoint": "attachments.create",
                "min_role": "member",
            },
        )
        async def upload_attachment(
            file_path: str,
            document_id: Optional[str] = None,
            content_type: Optional[str] = None,
        ) -> str:
            """
            Upload a local file to Outline and return its attachment link.

            Reads the file at ``file_path``, creates an attachment record,
            and uploads the bytes using the presigned mode returned by
            Outline (POST form or PUT). The MIME type is inferred from the
            filename unless ``content_type`` is provided.

            Use this tool when you need to:
            - Upload a file from the local filesystem to Outline
            - Get an attachment ID and link for use in a document
            - Attach an image, PDF, or other file to a document

            Args:
                file_path: Path to the local file to upload.
                document_id: Optional document to attach the file to.
                content_type: Optional MIME type override, such as
                    "application/pdf" or "image/png".

            Returns:
                Attachment ID, stable URL, and Markdown link.
            """
            try:
                path = Path(file_path).expanduser()
                if not path.is_file():
                    return f"Error: File not found: {file_path}"

                content = path.read_bytes()
                resolved_content_type = content_type or _guess_content_type(
                    path.name
                )

                client = await get_outline_client()
                attachment = await client.upload_attachment(
                    path.name,
                    content,
                    resolved_content_type,
                    document_id,
                )

                attachment_id = attachment.get("id", "unknown")
                name = attachment.get("name", path.name)
                url = attachment.get("url") or (
                    f"{client.api_url}/attachments.redirect?id={attachment_id}"
                )

                return (
                    "Attachment uploaded successfully.\n"
                    f"Name: {name}\n"
                    f"Attachment ID: {attachment_id}\n"
                    f"URL: {url}\n"
                    f"Markdown: [{name}]({url})"
                )
            except OutlineClientError as e:
                return f"Error uploading attachment: {str(e)}"
            except OSError as e:
                return f"Error reading file: {str(e)}"
            except Exception as e:
                return f"Unexpected error: {str(e)}"
