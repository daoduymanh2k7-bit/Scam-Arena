"""Shared normalization for the editable intent phrase catalog."""

from __future__ import annotations

import re
import unicodedata


def normalize_phrase(text: str) -> str:
    value = unicodedata.normalize("NFD", text.casefold())
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    value = value.replace("đ", "d")
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()
