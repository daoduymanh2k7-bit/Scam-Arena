from __future__ import annotations

REFUSAL_KEYWORDS = (
    "không", "từ chối", "gọi lại", "tổng đài", "gặp trực tiếp", "báo công an",
    "không cung cấp", "cúp máy", "cúp điện thoại",
)


def is_refusal(text: str) -> bool:
    lowered = text.casefold()
    return any(keyword in lowered for keyword in REFUSAL_KEYWORDS)
