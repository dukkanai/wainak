"""Manual loopback-only preview. Does not run unless explicitly requested."""

import argparse
from wsgiref.simple_server import WSGIRequestHandler, make_server

from .api import DevelopmentApplication


class NoContentLogs(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description="Synthetic Wainak preview; not for real accounts or production.")
    parser.add_argument("--development", action="store_true", help="Required explicit opt-in to volatile synthetic mode")
    parser.add_argument("--port", type=int, default=8089)
    args = parser.parse_args()
    if not args.development:
        parser.error("--development is required; there is no production server")
    if not 1024 <= args.port <= 65535:
        parser.error("choose an unprivileged port from 1024 to 65535")
    app = DevelopmentApplication(enable_development=True)
    print("SYNTHETIC DEVELOPMENT ONLY. No mail, payment, identity verification, or durable storage.", flush=True)
    with make_server("127.0.0.1", args.port, app, handler_class=NoContentLogs) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
