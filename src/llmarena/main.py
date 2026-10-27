from __future__ import annotations

import argparse
import sys

from llmarena.settings import Settings


def cli(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="llm-arena", description="Arena onde dois LLMs lutam escrevendo código."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="sobe o servidor web")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--fake", action="store_true", help="modo demo sem chaves de API")
    verify = sub.add_parser("verify-challenges", help="valida o banco de desafios no sandbox")
    verify.add_argument("path", nargs="?", default=None)
    args = parser.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn

        from llmarena.app import create_app

        overrides = {k: v for k, v in {"host": args.host, "port": args.port}.items() if v is not None}
        if args.fake:
            overrides["fake_providers"] = True
        settings = Settings(**overrides)
        uvicorn.run(
            create_app(settings), host=settings.host, port=settings.port, log_level=settings.log_level.lower()
        )
    elif args.cmd == "verify-challenges":
        from llmarena.challenges.verify import main as verify_main

        sys.exit(verify_main(args.path or str(Settings().bank_path)))


if __name__ == "__main__":
    cli()
