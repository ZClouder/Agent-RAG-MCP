import sys

from src.mcp_server.server import main as mcp_server_main


def main() -> int:
    """Run the real MCP stdio server."""
    return mcp_server_main()


if __name__ == "__main__":
    sys.exit(main())
