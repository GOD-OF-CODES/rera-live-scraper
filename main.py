"""Start the live, request-driven RERA scraper. No database setup is needed."""
import argparse
from src.live_api import app  # ASGI entrypoint for Vercel


def main():
    parser = argparse.ArgumentParser(description="Run the live UP-RERA scraper (no database).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    import uvicorn
    print(f"Live project search: http://{args.host}:{args.port}", flush=True)
    uvicorn.run("src.live_api:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
