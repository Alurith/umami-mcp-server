from __future__ import annotations


def main() -> None:
    """Run the Umami MCP server over stdio."""

    from .server import run

    run()
