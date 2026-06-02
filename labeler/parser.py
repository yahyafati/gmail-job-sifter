import base64
from datetime import timezone, datetime
from email.utils import parsedate_to_datetime
from typing import Dict, Any, List, Optional

from bs4 import BeautifulSoup

from classifier.types import FetchedEmailObject


def decode_base64url(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode(
        "utf-8", errors="replace"
    )


def extract_bodies(payload: Dict[str, Any]) -> Dict[str, List[str]]:
    text_parts: List[str] = []
    html_parts: List[str] = []

    def walk(part: Dict[str, Any]) -> None:
        mime_type = part.get("mimeType", "")
        body_data = part.get("body", {}).get("data")
        parts = part.get("parts", [])

        if mime_type == "text/plain" and body_data:
            text_parts.append(decode_base64url(body_data))
        elif mime_type == "text/html" and body_data:
            html_parts.append(decode_base64url(body_data))

        for child in parts:
            walk(child)

    walk(payload)
    return {"text": text_parts, "html": html_parts}


def normalize_email_date(date_value: Optional[str]) -> Optional[datetime]:
    if not date_value:
        return None

    try:
        parsed = parsedate_to_datetime(date_value)

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    except (TypeError, ValueError, IndexError):
        return None


def parse_message(raw_message: Dict[str, Any]) -> FetchedEmailObject:
    payload = raw_message.get("payload", {})
    header_list = payload.get("headers", [])
    headers = {header["name"]: header["value"] for header in header_list}

    bodies = extract_bodies(payload)
    body_text = "\n".join(part for part in bodies["text"] if part).strip()
    if not body_text and bodies["html"]:
        html_blob = "\n".join(bodies["html"])
        body_text = (
            BeautifulSoup(html_blob, "html.parser").get_text(separator="\n").strip()
        )

    date = normalize_email_date(headers.get("Date"))

    return FetchedEmailObject(
        message_id=raw_message.get("id") or "",
        subject=headers.get("Subject") or "",
        body=body_text,
        sender=headers.get("From") or "",
        date=date,
    )
