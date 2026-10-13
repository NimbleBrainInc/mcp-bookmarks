"""Mint a development token for a local server.

Production tokens come from a real authorization server, and the server verifies them
against that server's published keys (BOOKMARKS_JWKS_URI). For a laptop there is no such
server, so this script plays one: it keeps an RSA key pair in .dev-keys/ and signs tokens
whose `aud` is the local server's own URL, which is the one claim the server insists on.

    uv run python scripts/dev_token.py --sub alice

prints a token and the environment the server needs to accept it.
"""

import argparse
import os
from pathlib import Path

from fastmcp.server.auth.providers.jwt import RSAKeyPair

KEYS = Path(".dev-keys")
ISSUER = os.environ.get("BOOKMARKS_ISSUER", "https://dev-issuer.invalid")
PUBLIC_URL = os.environ.get("BOOKMARKS_PUBLIC_URL", "http://127.0.0.1:8000")


def load_or_create() -> RSAKeyPair:
    private, public = KEYS / "private.pem", KEYS / "public.pem"
    if private.exists() and public.exists():
        from pydantic import SecretStr

        return RSAKeyPair(private_key=SecretStr(private.read_text()), public_key=public.read_text())
    KEYS.mkdir(exist_ok=True)
    pair = RSAKeyPair.generate()
    private.write_text(pair.private_key.get_secret_value())
    private.chmod(0o600)
    public.write_text(pair.public_key)
    return pair


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sub", default="alice", help="who the token is for (the owner)")
    parser.add_argument("--hours", type=float, default=8.0)
    args = parser.parse_args()

    pair = load_or_create()
    audience = PUBLIC_URL.rstrip("/") + "/mcp"
    token = pair.create_token(
        subject=args.sub,
        issuer=ISSUER,
        audience=audience,
        expires_in_seconds=int(args.hours * 3600),
    )
    print(f"# token for {args.sub!r}, aud={audience}, iss={ISSUER}")
    print(token)
    print()
    print("# run the server with (what `make run-auth` does):")
    print(f"BOOKMARKS_PUBLIC_URL={PUBLIC_URL} BOOKMARKS_ISSUER={ISSUER} \\")
    print(f"BOOKMARKS_PUBLIC_KEY_FILE={KEYS / 'public.pem'} uv run python -m mcp_bookmarks.server")


if __name__ == "__main__":
    main()
