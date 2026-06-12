"""Собирает .streamlit/secrets.toml из service-account.json."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "service-account.json"
TOML_PATH = ROOT / ".streamlit" / "secrets.toml"
SPREADSHEET_ID = "1mQiNJ_3XAimSraS3Wf5pWIFhkr8UWqJ7NlIoQvXoPkM"


def main() -> None:
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    private_key = data["private_key"].replace("\\n", "\n").strip()
    toml = f"""[gcp_service_account]
type = "{data['type']}"
project_id = "{data['project_id']}"
private_key_id = "{data['private_key_id']}"
client_email = "{data['client_email']}"
client_id = "{data['client_id']}"
auth_uri = "{data['auth_uri']}"
token_uri = "{data['token_uri']}"
auth_provider_x509_cert_url = "{data['auth_provider_x509_cert_url']}"
client_x509_cert_url = "{data['client_x509_cert_url']}"
universe_domain = "{data['universe_domain']}"

private_key = \"\"\"
{private_key}
\"\"\"

[references]
spreadsheet_id = "{SPREADSHEET_ID}"
"""
    TOML_PATH.write_text(toml, encoding="utf-8")
    print(f"Wrote {TOML_PATH}")


if __name__ == "__main__":
    main()
