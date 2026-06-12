import tomllib
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

ROOT = Path(__file__).resolve().parents[1]
info = tomllib.loads((ROOT / ".streamlit" / "secrets.toml").read_text(encoding="utf-8"))[
    "gcp_service_account"
]
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
refs = tomllib.loads((ROOT / ".streamlit" / "secrets.toml").read_text(encoding="utf-8")).get(
    "references", {}
)
client = gspread.authorize(Credentials.from_service_account_info(info, scopes=scopes))
if refs.get("ssl_verify") is False:
    client.http_client.session.verify = False
sheet = client.open_by_key("1mQiNJ_3XAimSraS3Wf5pWIFhkr8UWqJ7NlIoQvXoPkM")
rows = len(sheet.worksheet("contractors").get_all_values())
print(f"OK: {sheet.title}, contractors rows={rows}")
