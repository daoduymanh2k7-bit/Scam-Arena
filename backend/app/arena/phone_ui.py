"""Keep service dialogue grounded in the simulated phone's actual screens."""
import re
from app.arena.normalization import normalize_phrase


def unsupported_screen_request(text):
    line=normalize_phrase(text)
    return bool(re.search(r'man hinh.*(?:hien thi|hien gi)|(?:mo|vao) (?:ung dung|gmail|app).*?(?:dat lich|da dung|ngan hang|truoc do)',line))


def service_ui_line(family, facts, *, reading=False):
    if reading and family=='appointment':
        return f"Trong thư có lịch bảo trì {facts.get('window','đã hẹn')} tại {facts.get('place','điểm hẹn')}. Lịch này có đúng với lịch anh/chị đã đặt không?"
    if reading and family=='delivery':
        return 'Anh/chị xem thông tin đơn trong thư xác nhận nhé. Anh/chị muốn nhận tại điểm hẹn hay đổi thời gian nhận?'
    if reading and family=='support':
        return 'Anh/chị đang xem thư xác nhận phiếu hỗ trợ. Anh/chị mô tả lỗi đang gặp để tôi ghi nhận nhé?'
    return 'Anh/chị bấm Tiện ích trên điện thoại mô phỏng, chọn Xem hồ sơ / đơn / lịch để đối chiếu; hoặc mở thư xác nhận trong hộp thư nhé.'


def screen_feedback(payload, action, caller, player, facts):
    if action!='other' or payload.get('family') not in {'appointment','delivery','support'}:
        return None
    previous=normalize_phrase(caller)
    if not re.search(r'man hinh|mo.*(?:ung dung|app)|(?:xem|kiem tra|doi chieu).*(?:lich|thu|ho so)',previous):
        return None
    text=normalize_phrase(player)
    if re.search(r'\b(?:gmail|email|mail|hop thu)\b',text):
        return service_ui_line(payload['family'],facts,reading=True)
    if re.search(r'khong (?:thay|co|hien)|mo o dau|ung dung nao|bam (?:o dau|cho nao)|hien thi gi',text):
        return service_ui_line(payload['family'],facts)
    return None


def ground_service_line(text, payload, facts):
    if payload.get('family') in {'appointment','delivery','support'} and unsupported_screen_request(text):
        return service_ui_line(payload['family'],facts)
    return text
