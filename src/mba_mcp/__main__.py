"""Entry point: run the MCP server, or authorise Gmail from a terminal."""

from __future__ import annotations

import sys

from .config import get_config


def main() -> int:
    args = sys.argv[1:]
    command = args[0] if args else "serve"

    if command in {"-h", "--help", "help"}:
        print(__doc__)
        print("\nUsage:\n  mba-mcp [serve]   run the MCP server on stdio")
        print("  mba-mcp auth      run the Gmail OAuth consent flow")
        print("  mba-mcp info      show resolved paths and configuration")
        return 0

    config = get_config()
    config.ensure_data_dir()

    if command == "auth":
        from . import gmail

        try:
            token = gmail.authorize(config)
        except gmail.GmailNotConfigured as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"Gmail authorised. Token cached at {token}")
        return 0

    if command == "info":
        print(f"data dir:        {config.data_dir}")
        print(f"database:        {config.db_path}")
        print(f"track:           {config.track}")
        print(f"school:          {config.school or '(unset)'}")
        print(f"base CV:         {config.base_cv}")
        print(f"gmail secret:    {config.gmail_client_secret}")
        print(f"gmail token:     {config.gmail_token}")
        print(f"adzuna:          {'configured' if config.adzuna_enabled else 'not configured'}")
        return 0

    if command != "serve":
        print(f"unknown command: {command}", file=sys.stderr)
        return 2

    from .server import main as serve

    serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
