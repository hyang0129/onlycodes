import argparse
import sys
from myapp.server import start
from myapp.config import get_config

server_url = "http://localhost:8080"


def main():
    parser = argparse.ArgumentParser(description="myapp server CLI")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--dry-run", action="store_true", help="Print config and exit without starting")
    args = parser.parse_args()

    config = get_config()
    print(f"Using config: {config}")

    if args.dry_run:
        print(f"[dry-run] Would start server at {args.host}:{args.port} (debug={args.debug})")
        return 0

    result = start(args.host, args.port, args.debug)
    print(f"Server started: {result.to_dict()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
