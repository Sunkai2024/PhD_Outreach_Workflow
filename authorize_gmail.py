"""Create a local Gmail OAuth token. This command never sends email."""

import argparse
from pathlib import Path


SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, required=True, help="Desktop OAuth client JSON")
    parser.add_argument("--token", type=Path, required=True, help="Private output token JSON")
    parser.add_argument("--port", type=int, default=8765, help="Local callback port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Print the URL instead of opening a browser")
    args = parser.parse_args()
    client_path = args.credentials.expanduser().resolve()
    token_path = args.token.expanduser().resolve()
    if not client_path.is_file():
        parser.error("OAuth client JSON not found; download a Desktop app client from Google Cloud.")
    if token_path == client_path:
        parser.error("--token must differ from --credentials.")
    try:
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        parser.exit(1, "Install Gmail dependencies: python -m pip install -r requirements-gmail.txt\n")

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path))
        if not creds.has_scopes(SCOPES):
            creds = None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            creds = None
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
        creds = flow.run_local_server(
            host="127.0.0.1", port=args.port, open_browser=not args.no_browser,
            access_type="offline", prompt="consent",
        )
    if not creds.refresh_token:
        parser.exit(1, "No refresh token returned; revoke the previous grant and authorize again.\n")
    token_path.parent.mkdir(parents=True, exist_ok=True)
    # Create with owner-only permissions before writing any credential content.
    import os
    descriptor = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        if os.name == "posix":
            os.fchmod(output.fileno(), 0o600)
        output.write(creds.to_json())
    print(f"OAuth token saved to: {token_path}")
    print("No email was sent. Keep this file private.")


if __name__ == "__main__":
    main()
