"""Rasa-first Vietnamese intent detection with deterministic safety rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
import unicodedata

from app.arena.normalization import normalize_phrase


class Intent(str, Enum):
    VERIFY = "verify"
    REFUSE = "refuse"
    DOUBT = "doubt"
    COMPLY = "comply"
    SHARE_SENSITIVE = "share_sensitive"
    TRANSFER_MONEY = "transfer_money"
    HANG_UP = "hang_up"
    UNKNOWN = "unknown"


class RequestedAction(str, Enum):
    NONE = "none"
    SHARE_SENSITIVE = "share_sensitive"
    TRANSFER_MONEY = "transfer_money"
    INSTALL_APP = "install_app"
    CLICK_LINK = "click_link"
    SHARE_SCREEN = "share_screen"
    KEEP_SECRET = "keep_secret"
    OTHER = "other"


@dataclass(frozen=True)
class IntentResult:
    intent: Intent
    matched_rule: str | None = None
    evidence: str | None = None


_SENSITIVE_OBJECT = (
    r"(?:otp|o\s*t\s*p|ô\s*tê\s*pê|mã\s*(?:xác\s*thực|xac\s*thuc|"
    r"bảo\s*mật|bao\s*mat|khôi\s*phục|khoi\s*phuc)|mật\s*khẩu|mat\s*khau|"
    r"password|mã\s*cvv|cvv|cvc|số\s*thẻ|so\s*the|cccd|căn\s*cước|can\s*cuoc)"
)
_SENSITIVE_ACTION = r"(?:đọc|doc|gửi|gui|cung\s*cấp|cung\s*cap|chia\s*sẻ|chia\s*se|nhập|nhap|đưa|dua|tiết\s*lộ|tiet\s*lo)"
_TRANSFER_ACTION = r"(?:chuyển\s*khoản|chuyen\s*khoan|chuyển\s*tiền|chuyen\s*tien|gửi\s*tiền|gui\s*tien|nộp\s*tiền|nop\s*tien|thanh\s*toán|thanh\s*toan)"

_SENSITIVE_DISCLOSURE_PATTERNS = (
    re.compile(rf"\b{_SENSITIVE_ACTION}\b.{{0,45}}\b{_SENSITIVE_OBJECT}\b"),
    re.compile(rf"\b{_SENSITIVE_OBJECT}\b.{{0,25}}\b(?:là|la|đây|day)\s*(?:mã\s*)?[a-z0-9]{{4,}}\b"),
    re.compile(rf"\b(?:đã|da|vừa|vua|lỡ|lo)\s+{_SENSITIVE_ACTION}\b.{{0,45}}\b{_SENSITIVE_OBJECT}\b"),
)
_TRANSFER_PATTERNS = (
    re.compile(rf"\b(?:tôi|toi|em|mình|minh|anh|chị|chi)\s+(?:(?:sẽ|se|đang|dang|đã|da|vừa|vua|đồng\s*ý|dong\s*y|chấp\s*nhận|chap\s*nhan)\s+)?{_TRANSFER_ACTION}\b"),
    re.compile(rf"\b(?:đã|da|vừa|vua|lỡ|lo)\s+{_TRANSFER_ACTION}\b"),
    re.compile(rf"\b{_TRANSFER_ACTION}\s+(?:ngay|liền|lien|bây\s*giờ|bay\s*gio)\b"),
)
_HANG_UP_PATTERNS = (
    re.compile(r"\b(?:tôi|toi|em|mình|minh)?\s*(?:sẽ\s*)?(?:cúp\s*máy|cup\s*may|ngắt\s*cuộc\s*gọi|ngat\s*cuoc\s*goi|kết\s*thúc\s*cuộc\s*gọi|ket\s*thuc\s*cuoc\s*goi)\b"),
    re.compile(r"\b(?:tôi|toi|em|mình|minh)\s+(?:sẽ\s+)?(?:chặn|chan)\s+số\s+này\b"),
)
_VERIFY_PATTERNS = (
    re.compile(r"\b(?:tự\s*)?(?:gọi|goi|liên\s*hệ|lien\s*he|tra\s*cứu|tra\s*cuu)\b.{0,60}\b(?:hotline|tổng\s*đài|tong\s*dai|số\s*chính\s*thức|so\s*chinh\s*thuc|số\s*trên\s*thẻ|so\s*tren\s*the|chi\s*nhánh|ứng\s*dụng\s*chính\s*thức|ung\s*dung\s*chinh\s*thuc|ngân\s*hàng|ngan\s*hang|cơ\s*quan|co\s*quan)\b"),
    re.compile(r"\b(?:tự\s*)?(?:xác\s*minh|xac\s*minh|kiểm\s*tra|kiem\s*tra)\b.{0,50}\b(?:kênh\s*chính\s*thức|kenh\s*chinh\s*thuc|ngân\s*hàng|ngan\s*hang|cơ\s*quan|co\s*quan)\b"),
    re.compile(r"\b(?:tôi|toi|em|mình|minh)\s+(?:sẽ\s+)?(?:đến|den|tới|toi)\s+(?:chi\s*nhánh|trụ\s*sở|tru\s*so)\b"),
)
_REFUSAL_PATTERNS = (
    re.compile(r"\b(?:từ\s*chối|tu\s*choi|không\s*đồng\s*ý|khong\s*dong\s*y|không\s*làm\s*theo|khong\s*lam\s*theo|đừng\s*hòng|dung\s*hong)\b"),
    re.compile(rf"\b(?:không|khong|chẳng|chang|chưa|chua|đừng|dung|tuyệt\s*đối\s*không|tuyet\s*doi\s*khong)\b.{{0,45}}\b(?:{_SENSITIVE_ACTION}|{_TRANSFER_ACTION}|cài|cai|bấm|bam|nhấn|nhan|chia\s*sẻ|chia\s*se|làm\s*theo|lam\s*theo)\b"),
    re.compile(r"\b(?:không|khong|chẳng|chang|chưa|chua|đừng|dung)\s+(?:cung\s*cấp|cung\s*cap|chia\s*sẻ|chia\s*se|đọc|doc|gửi|gui|chuyển|chuyen|cài|cai|bấm|bam)\b"),
)
_COMPLIANCE_PATTERNS = (
    re.compile(r"\b(?:tôi|toi|em|mình|minh)\s+(?:sẽ|se|đồng\s*ý|dong\s*y|chấp\s*nhận|chap\s*nhan)\s+(?:làm\s*theo|lam\s*theo|cài|cai|bấm|bam|nhấn|nhan|mở|mo|giữ\s*bí\s*mật|giu\s*bi\s*mat|chia\s*sẻ\s*màn\s*hình|chia\s*se\s*man\s*hinh)\b"),
    re.compile(r"\b(?:tôi|toi|em|mình|minh)\s+(?:sẽ|se)\s+(?:làm|lam)\s+theo\b"),
    re.compile(r"\b(?:tôi|toi|em|mình|minh)\s+(?:làm|lam)\s+theo\b"),
)
_DOUBT_PATTERNS = (
    re.compile(r"\b(?:sao|tại\s*sao|tai\s*sao|vì\s*sao|vi\s*sao)\b.{0,70}\b(?:otp|mã|ma|chuyển|chuyen|tài\s*khoản|tai\s*khoan|ngân\s*hàng|ngan\s*hang)\b"),
    re.compile(r"\b(?:nghe|thấy|thay)\b.{0,30}\b(?:không\s*ổn|khong\s*on|đáng\s*ngờ|dang\s*ngo|lạ|la|bất\s*thường|bat\s*thuong)\b"),
    re.compile(r"\b(?:nghi\s*ngờ|không\s*tin|khong\s*tin|không\s*chắc|khong\s*chac|có\s*thật\s*không|co\s*that\s*khong)\b"),
    re.compile(r"\b(?:lừa\s*đảo|lua\s*dao|scam|gian\s*lận|gian\s*lan|khả\s*nghi|kha\s*nghi|đáng\s*ngờ|dang\s*ngo)\b"),
)
# Very short confirmations have no stable intent without knowing what was asked.
_AFFIRMATIVE_ONLY = re.compile(r"^(?:vâng|vang|dạ|da|được|duoc|ok|okay|ừ|u|có|co|rồi|roi|đồng ý|dong y|chấp nhận|chap nhan|tôi làm|toi lam|em làm|em lam|làm ngay|lam ngay)$")
_CONTEXTUAL_YES = re.compile(
    r"(?:(?:da|vang) )?(?:duoc(?: roi)?|ok(?:ay)?|u|co|roi|dong y|chap nhan|"
    r"(?:toi|em|minh) lam|lam ngay)(?: a| nhe)?|(?:da|vang)(?: a)?"
)
_CONTEXTUAL_NO = re.compile(r"(?:da )?(?:khong|chua)(?: a| dau| nhe)?")
_WAIT_AND_SEE = re.compile(
    r"(?:(?:da|vang|u|ok|duoc(?: roi)?) )?(?:de )?(?:(?:toi|em|minh) )?"
    r"(?:xem|kiem tra|suy nghi)(?: lai| them)?(?: da| sau)?(?: a| nhe)?"
)
_NEUTRAL_PROMPT = re.compile(
    r"\b(?:nghe (?:may|ro)|con nghe|tien nghe|co nghe|nhan duoc|da nhan|"
    r"co ranh|dang ban|tien noi chuyen|tiep tuc nghe|muon nghe)\b"
)
_OFFICIAL_CHANNEL = (
    r"(?:tong dai|hotline|so tren the|(?:kenh|so|ung dung|trang web) chinh thuc|chi nhanh|tru so)"
)
_VERIFY_PROMPT = re.compile(
    rf"\b(?:tu|muon|co the)\b.{{0,35}}?\b"
    rf"(?:goi|tra cuu|xac minh|kiem tra|lien he|den)\b.{{0,45}}\b{_OFFICIAL_CHANNEL}\b"
)
_REQUEST_PREFIX = r"(?:vui long|xin|hay|can|dong y|co the|giup toi|anh chi|anh|chi|em|ban)"
_RISKY_PROMPT = re.compile(
    rf"\b{_REQUEST_PREFIX}\s+(?:vui long |hay |can |co the |co dong y )?"
    r"(?:doc|gui|nhap|cung cap|chia se|dua)\b.{0,35}\b(?:otp|ma xac thuc|ma bao mat|mat khau|so the|cccd)\b"
    rf"|\b{_REQUEST_PREFIX}\s+(?:vui long |hay |can |co the |co dong y )?"
    r"(?:chuyen (?:tien|khoan|phi)|nop (?:tien|phi)|dong phi|thanh toan)\b"
)
_COMPLY_PROMPT = re.compile(
    r"\b(?:dong y lam theo|(?:dung|khong duoc) (?:ngat may|ke voi ai))\b"
    rf"|\b{_REQUEST_PREFIX}\s+(?:vui long |hay |can |co the |co dong y )?"
    r"(?:lam theo (?:huong dan|yeu cau)|"
    r"(?:bam|nhan|mo) (?:vao )?(?:(?:duong |lien )?link|duong dan|lien ket)|"
    r"cai (?:dat )?(?:ung dung|app)|chia se man hinh|giu bi mat)\b"
)
_NEGATION_MARKERS = ("không", "khong", "chẳng", "chang", "chưa", "chua", "đừng", "dung", "từ chối", "tu choi")


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text).casefold()
    normalized = re.sub(r"[^\w\s,;.!?]", " ", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip(" ,;.!?")


def _match(patterns: tuple[re.Pattern[str], ...], text: str) -> re.Match[str] | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match
    return None


def _is_negated(text: str, match: re.Match[str]) -> bool:
    """Check for a negator in the same short clause before a harmful action."""
    prefix = text[max(0, match.start() - 60):match.start()]
    # A comma/semicolon separates clauses; a negation before it does not cancel
    # an affirmative action in the next clause.
    prefix = re.split(r"[,;.!?]", prefix)[-1]
    words = prefix.split()
    return any(
        marker in " ".join(words[max(0, len(words) - 7):])
        for marker in _NEGATION_MARKERS
    )


def _coerce_requested_action(value: RequestedAction | str) -> RequestedAction:
    if isinstance(value, RequestedAction):
        return value
    try:
        return RequestedAction(value)
    except ValueError:
        return RequestedAction.OTHER


def _result(intent: Intent, rule: str, match: re.Match[str] | None, text: str) -> IntentResult:
    evidence = match.group(0) if match else text[:100]
    return IntentResult(intent=intent, matched_rule=rule, evidence=evidence)


def _contextual_reply(text: str, caller_line: str, action: RequestedAction) -> IntentResult | None:
    """Resolve short replies against the latest prompt before standalone NLU."""
    reply = normalize_phrase(text)
    if _WAIT_AND_SEE.fullmatch(reply):
        return IntentResult(Intent.UNKNOWN, evidence=text)
    agrees = _CONTEXTUAL_YES.fullmatch(reply)
    declines = _CONTEXTUAL_NO.fullmatch(reply)
    if not agrees and not declines:
        return None

    # A later question can change what a short yes/no refers to.
    clauses = [normalize_phrase(part) for part in re.split(r"[.!?;\n]+", caller_line)]
    prompt = next((part for part in reversed(clauses) if part), "")
    if _NEUTRAL_PROMPT.search(prompt):
        return _result(Intent.UNKNOWN, "contextual_acknowledgement", None, text)
    verify_match = _VERIFY_PROMPT.search(prompt)
    if agrees and verify_match and not _is_negated(prompt, verify_match):
        return _result(Intent.VERIFY, "contextual_verify", None, text)
    risky_request = _RISKY_PROMPT.search(prompt)
    compliance_request = _COMPLY_PROMPT.search(prompt)
    if risky_request or compliance_request:
        if declines and not reply.startswith(("chua", "da chua")):
            return _result(Intent.REFUSE, "contextual_refusal", None, text)
        # An acknowledgement alone cannot establish a high-impact action.
        # In financial/sensitive stages even comply can route to an unsafe ending.
        if risky_request or action in {RequestedAction.SHARE_SENSITIVE, RequestedAction.TRANSFER_MONEY}:
            return _result(Intent.UNKNOWN, "contextual_unconfirmed_action", None, text)
        if agrees:
            return _result(Intent.COMPLY, "contextual_affirmation", None, text)
    return IntentResult(Intent.UNKNOWN, evidence=text)


def _classify_brief_reply(text: str, caller_line: str, action: RequestedAction) -> IntentResult | None:
    fallback = _contextual_reply(text, caller_line, action)
    if fallback is None or (
        fallback.intent is Intent.UNKNOWN and fallback.matched_rule is not None
    ):
        return fallback

    reply = normalize_phrase(text)
    if _CONTEXTUAL_YES.fullmatch(reply):
        polarity = "yes"
        allowed = {Intent.VERIFY}
        if action not in {RequestedAction.SHARE_SENSITIVE, RequestedAction.TRANSFER_MONEY}:
            allowed.add(Intent.COMPLY)
    elif _CONTEXTUAL_NO.fullmatch(reply) and not reply.startswith(("chua", "da chua")):
        polarity = "no"
        allowed = {Intent.REFUSE}
    else:
        return fallback

    from app.arena.rasa_client import classify_context_with_rasa

    intent, confidence = classify_context_with_rasa(caller_line, polarity)
    if intent in allowed and fallback.intent in {Intent.UNKNOWN, intent}:
        return _result(intent, f"rasa:context:{confidence:.2f}", None, text)
    return fallback


def detect_intent(
    text: str,
    requested_action: RequestedAction | str = RequestedAction.NONE,
    *,
    scenario_id: int | None = None,
    caller_line: str | None = None,
) -> IntentResult:
    """Return one primary intent for a Vietnamese response.

    Rasa classifies ordinary utterances. When supplied, the actual caller line
    grounds short replies before they reach standalone NLU.
    """
    normalized = _normalize(text)
    action = _coerce_requested_action(requested_action)
    if not normalized:
        return IntentResult(Intent.UNKNOWN)

    # Short standalone refusals are common spoken answers and have a clear
    # meaning in a simulated call, even when the user omits the requested action.
    if normalized in {"không đồng ý", "khong dong y"} or (
        caller_line is None
        and normalized in {"không", "khong", "không ạ", "khong a", "không đâu", "khong dau", "không nhé", "khong nhe"}
    ):
        return _result(Intent.REFUSE, "standalone_refusal", None, normalized)

    # Harmful actions take precedence, but only when the matching action is
    # affirmative. Explicit negation is handled before safer intent rules.
    sensitive_match = _match(_SENSITIVE_DISCLOSURE_PATTERNS, normalized)
    if sensitive_match and not _is_negated(normalized, sensitive_match):
        return _result(Intent.SHARE_SENSITIVE, "affirmative_sensitive_disclosure", sensitive_match, normalized)

    transfer_match = _match(_TRANSFER_PATTERNS, normalized)
    if transfer_match and not _is_negated(normalized, transfer_match):
        return _result(Intent.TRANSFER_MONEY, "affirmative_money_transfer", transfer_match, normalized)

    hang_up_match = _match(_HANG_UP_PATTERNS, normalized)
    if hang_up_match:
        return _result(Intent.HANG_UP, "end_or_block_call", hang_up_match, normalized)

    if caller_line is not None:
        contextual_result = _classify_brief_reply(normalized, caller_line, action)
        if contextual_result is not None:
            return contextual_result
    elif _AFFIRMATIVE_ONLY.fullmatch(normalized):
        if action == RequestedAction.SHARE_SENSITIVE:
            return _result(Intent.SHARE_SENSITIVE, "contextual_affirmation_sensitive", None, normalized)
        if action == RequestedAction.TRANSFER_MONEY:
            return _result(Intent.TRANSFER_MONEY, "contextual_affirmation_transfer", None, normalized)
        if action not in {RequestedAction.NONE, RequestedAction.OTHER}:
            return _result(Intent.COMPLY, "contextual_affirmation", None, normalized)
        return IntentResult(Intent.UNKNOWN)

    # Rasa is the primary classifier for ordinary language. Deterministic
    # high-risk rules above take precedence; local phrase rules below are the
    # fallback when Rasa is unavailable or uncertain.
    from app.arena.rasa_client import classify_with_rasa

    rasa_intent, confidence = classify_with_rasa(text)
    if rasa_intent is not None and confidence >= 0.65:
        # Statistical guesses alone must never trigger high-impact outcomes.
        if rasa_intent not in {Intent.SHARE_SENSITIVE, Intent.TRANSFER_MONEY}:
            return IntentResult(
                intent=rasa_intent,
                matched_rule=f"rasa:{confidence:.2f}",
                evidence=normalized[:100],
            )

    verify_match = _match(_VERIFY_PATTERNS, normalized)
    if verify_match and not _is_negated(normalized, verify_match):
        return _result(Intent.VERIFY, "verify_independently", verify_match, normalized)

    refusal_match = _match(_REFUSAL_PATTERNS, normalized)
    if refusal_match:
        return _result(Intent.REFUSE, "explicit_refusal", refusal_match, normalized)

    compliance_match = _match(_COMPLIANCE_PATTERNS, normalized)
    if compliance_match:
        return _result(Intent.COMPLY, "explicit_compliance", compliance_match, normalized)

    doubt_match = _match(_DOUBT_PATTERNS, normalized)
    if doubt_match:
        return _result(Intent.DOUBT, "expressed_doubt", doubt_match, normalized)

    # Database phrase rules extend coverage for phrases that are useful to
    # scenario authors, while the high-confidence safety rules above stay in code.
    from app.database import get_active_intent_rules

    folded_text = normalize_phrase(text)
    regex_text = _normalize(text)
    hits: list[tuple[dict[str, object], re.Match[str], str]] = []
    ambiguous_negation = False
    for rule in get_active_intent_rules(scenario_id):
        try:
            if rule["match_type"] == "contains":
                phrase = rule["phrase_norm"] or normalize_phrase(rule["phrase"])
                match = re.search(re.escape(phrase), folded_text)
                match_text = folded_text
            else:
                match = re.search(rule["phrase"], regex_text, flags=re.IGNORECASE)
                match_text = regex_text
        except re.error:
            continue
        if match:
            if _is_negated(match_text, match):
                ambiguous_negation = True
            hits.append((rule, match, match_text))

    if hits:
        intents = {rule["intent"] for rule, _, _ in hits}
        if ambiguous_negation or len(intents) != 1:
            return IntentResult(Intent.UNKNOWN, evidence=normalized[:100])
        rule, match, match_text = max(hits, key=lambda hit: (hit[0]["priority"], -hit[0]["id"]))
        return _result(Intent(rule["intent"]), f"database_phrase:{rule['id']}", match, match_text)

    return IntentResult(Intent.UNKNOWN, evidence=normalized[:100])


def is_refusal(text: str) -> bool:
    """Legacy helper kept for callers outside the new branching engine."""
    lowered = text.casefold()
    return any(keyword in lowered for keyword in ("không", "từ chối", "tổng đài", "gặp trực tiếp", "không cung cấp", "báo công an"))
