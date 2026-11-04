from __future__ import annotations

from app.schemas import CallSession, DialogueTurn, RiskLevel, ScorerFlag

TRAP_KEYWORDS = {
    "đọc otp": ("đã đọc/xác nhận mã OTP cho đối phương", RiskLevel.HIGH),
    "chuyển khoản": ("đồng ý chuyển tiền theo yêu cầu", RiskLevel.HIGH),
    "số cccd": ("cung cấp số CCCD cho đối phương", RiskLevel.MEDIUM),
    "mật khẩu": ("cung cấp mật khẩu/tài khoản ngân hàng", RiskLevel.HIGH),
}
IMPROVEMENT_TIPS = {
    "đã đọc/xác nhận mã OTP cho đối phương": "Không bao giờ đọc mã OTP cho bất kỳ ai, kể cả người tự xưng là nhân viên ngân hàng.",
    "đồng ý chuyển tiền theo yêu cầu": "Hãy xác minh qua hotline chính thức trước khi chuyển tiền theo yêu cầu qua điện thoại.",
    "cung cấp số CCCD cho đối phương": "Hạn chế cung cấp giấy tờ tùy thân qua điện thoại; hãy xác minh qua kênh chính thức.",
    "cung cấp mật khẩu/tài khoản ngân hàng": "Không cung cấp mật khẩu qua điện thoại hoặc tin nhắn.",
}
NEGATION_WORDS = ("không", "đừng", "chưa", "từ chối", "không hề", "tuyệt đối không")
NEGATION_WINDOW_CHARS = 24
PANIC_LATENCY_THRESHOLD_SECONDS = 3.0
PANIC_MAX_WORDS = 4


def _is_negated(text: str, keyword: str) -> bool:
    index = text.find(keyword)
    if index < 0:
        return False
    context = text[max(0, index - NEGATION_WINDOW_CHARS):index]
    return any(word in context for word in NEGATION_WORDS)


def score_session(session_id: str, scenario_type: str, transcript: list[DialogueTurn]) -> CallSession:
    mistakes: list[ScorerFlag] = []
    score = 100
    latencies: list[float] = []

    for index, turn in enumerate(transcript):
        if turn.role != "user":
            continue
        if turn.elapsed_seconds is not None:
            latency = max(0.0, turn.elapsed_seconds)
            latencies.append(latency)
            if latency < PANIC_LATENCY_THRESHOLD_SECONDS and len(turn.text.split()) <= PANIC_MAX_WORDS:
                mistakes.append(ScorerFlag(
                    turn_index=index,
                    mistake=f"Phản hồi nhanh ({latency:.1f}s) và ngắn; có thể bạn chưa kịp suy nghĩ.",
                    severity=RiskLevel.MEDIUM,
                ))
                score -= 10

        lowered = turn.text.casefold()
        for keyword, (mistake, severity) in TRAP_KEYWORDS.items():
            if keyword in lowered and not _is_negated(lowered, keyword):
                mistakes.append(ScorerFlag(turn_index=index, mistake=mistake, severity=severity))
                score -= 30 if severity == RiskLevel.HIGH else 15

    score = max(score, 0)
    badge = "🏆 Cảnh giác cao" if score >= 80 else "🥈 Cần luyện thêm" if score >= 50 else "⚠️ Dễ bị lừa"
    return CallSession(
        session_id=session_id,
        scenario_type=scenario_type,
        transcript=transcript,
        mistakes=mistakes,
        user_score=score,
        badge=badge,
        avg_response_latency=sum(latencies) / len(latencies) if latencies else None,
    )


def improvement_tip(mistake: str) -> str:
    return IMPROVEMENT_TIPS.get(mistake, "Bình tĩnh xác minh thông tin qua kênh chính thức trước khi hành động.")
