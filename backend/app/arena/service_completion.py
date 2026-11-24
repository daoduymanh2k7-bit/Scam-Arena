"""Deterministic completion of low-risk tasks in the built-in service calls."""
import re
from dataclasses import dataclass
from app.arena.normalization import normalize_phrase


@dataclass(frozen=True)
class Completion:
    reason: str
    closing: str


def service_completion(payload, node_key, requested_action, caller_line, user_text, intent):
    family = payload.get('family')
    if (payload.get('scenario_kind') != 'benign' or requested_action != 'other'
            or payload.get('id') != f'practice-{family}-ordinary-' + str({'beginner':1,'intermediate':2,'advanced':3}.get(payload.get('difficulty'),0))
            or (node_key not in {'intro','details','confirmation'} and not (node_key=='verification' and family=='appointment' and 'lich nay co dung voi lich' in normalize_phrase(caller_line)))
            or intent in {'refuse','hang_up','share_sensitive','transfer_money'}):
        return None
    text = normalize_phrase(user_text)
    caller = normalize_phrase(caller_line)
    complaint = bool(re.search(r'\bkhong (?:mo|dang nhap|su dung|truy cap|vao).*?(?:duoc|ung dung)\b',text))
    if re.search(r'\bkhong\b',text) and not (family == 'support' and complaint):
        return None
    # Questions, hesitation, refusal and contradictory clauses still need a reply.
    if ('?' in user_text or re.search(r'\b(?:chua|nhung|co le|hinh nhu|de toi xem|tai sao|the nao|lam sao|bao nhieu|o dau|khi nao|bao gio)\b',text)
            or 'đừng' in user_text.casefold()):
        return None
    acknowledgement = bool(re.fullmatch(r'(?:vang|da|duoc|dong y|ok|oke|u|uh|roi)(?: a| nhe| roi)?',text))
    slot = r'\b(?:[01]?\d|2[0-3])\s*(?:gio|h)(?:\s*[0-5]?\d)?\b'
    when = bool(re.search(slot,text) or re.fullmatch(r'(?:hen |giao |nhan |de |vao )?(?:sang|trua|chieu|toi) (?:nay|mai)(?: nhe| di| a)?',text))
    if family == 'delivery':
        place = bool(re.search(r'\b(?:o|tai|xuong|de o|giao o|nhan o) (?:sanh|cong|cua|quay|diem hen|bao ve)\b',text)
                     or re.fullmatch(r'(?:sanh|cong|quay tiep nhan)(?: di| nhe| a)?',text))
        relevant = bool(re.search(r'\b(?:nhan|giao|dia diem|vi tri|thoi gian|lich|hen)\b',caller))
        if relevant and (place or when or re.search(r'\b(?:cu theo lich|theo lich cu|toi se xuong nhan)\b',text)
                         or (node_key == 'confirmation' and acknowledgement)):
            return Completion('delivery_arranged','Vâng, tôi ghi nhận thời gian và địa điểm nhận hàng mình vừa thống nhất. Cảm ơn anh/chị, tôi kết thúc cuộc gọi tại đây.')
    elif family == 'appointment':
        relevant = bool(re.search(r'\b(?:lich|hen|gio|tien)\b',caller))
        if relevant and (when or acknowledgement or re.search(r'\b(?:dung lich|theo lich|xac nhan lich|van tien|giu nguyen lich)\b',text)):
            return Completion('appointment_confirmed','Vâng, tôi ghi nhận lịch hẹn mình vừa thống nhất. Anh/chị có thể đối chiếu trong thư xác nhận. Cảm ơn anh/chị, tôi kết thúc cuộc gọi tại đây.')
    elif family == 'support':
        resolved = bool(re.search(r'\b(?:da het loi|het loi roi|da lam duoc|chay binh thuong|hoat dong binh thuong|da sua duoc)\b',text))
        if resolved:
            return Completion('support_resolved','Vâng, tôi ghi nhận anh/chị đã sử dụng lại bình thường. Cảm ơn anh/chị đã trao đổi, tôi kết thúc cuộc gọi tại đây.')
        description = complaint or bool(re.search(r'\b(?:bi loi|bao loi|bi thoat|bi treo|dung hinh|man hinh trang|mo ung dung la|loi khi)\b',text))
        requested = bool(re.search(r'\b(?:mo ta|loi|trieu chung)\b',caller))
        if description and requested:
            return Completion('support_issue_recorded','Vâng, tôi đã ghi nhận nội dung lỗi anh/chị vừa mô tả vào phiếu hỗ trợ để tiếp tục xử lý. Cảm ơn anh/chị, tôi kết thúc cuộc gọi tại đây.')
    return None
