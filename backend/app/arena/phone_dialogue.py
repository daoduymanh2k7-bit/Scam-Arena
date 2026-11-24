"""Phone-only presentation and explicit clarification cues; never assign intent."""
import re
from app.arena.normalization import normalize_phrase


def phone_opening(text):
    original = text.strip()
    text = re.sub(r"^(?:alo|alô|a lô|(?:xin\s+)?chào)(?:\s+anh(?:/|\s+)chị)?(?=[\s,.!?…:]|$)[\s,.!?…:]*", "", original, flags=re.I) or original
    # Courtesy has already happened before the stored scenario opening.
    rest = re.sub(r"^(?:xin phép hỏi\s+)?anh(?:/|\s+)chị\s+có tiện nghe máy[^?]*\?\s*", "", text, flags=re.I)
    return rest or text


def listening_acknowledgement(text):
    text = normalize_phrase(text)
    return bool(re.search(r"\b(?:dang|van|con) nghe\b", text)) and not re.search(r"\b(?:khong|chua|chang)\b", text)


def clarification_fallback(player_text, caller_line, default, category):
    text = normalize_phrase(player_text)
    asks_transaction = bool(re.search(r"\bgiao dich (?:gi|nao)\b", text))
    if asks_transaction and category == "bank_impersonation":
        return "Tôi đang nói về giao dịch mà hệ thống báo cần kiểm tra trên tài khoản ngân hàng của anh/chị."
    if listening_acknowledgement(player_text):
        topics = {
            "bank_impersonation": "Tôi gọi để trao đổi về giao dịch cần kiểm tra trên tài khoản ngân hàng của anh/chị.",
            "fake_prize": "Tôi gọi để trao đổi về thông báo trúng thưởng và cách xác nhận giải.",
            "law_enforcement_impersonation": "Tôi cần trao đổi về hồ sơ tài chính vừa nhắc tới.",
        }
        return topics.get(category, default)
    return default
