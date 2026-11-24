from app.arena.phone_ui import screen_feedback, ground_service_line
from app.arena.line_generator import validate_line

PAYLOAD={'family':'appointment'}
FACTS={'window':'chiều nay','place':'quầy tiếp nhận'}
CALLER='Anh/chị mở ứng dụng đặt lịch, cho tôi biết màn hình đang hiển thị gì.'


def test_mail_feedback_answers_specific_content_instead_of_repeating_screen_request():
    line=screen_feedback(PAYLOAD,'other',CALLER,'Hiển thị Gmail',FACTS)
    assert 'chiều nay' in line and 'quầy tiếp nhận' in line
    assert 'đúng với lịch' in line and 'màn hình' not in line


def test_missing_screen_points_to_existing_phone_utilities():
    line=screen_feedback(PAYLOAD,'other',CALLER,'Không thấy gì, mở ở đâu?',FACTS)
    assert 'Tiện ích' in line and 'Xem hồ sơ / đơn / lịch' in line


def test_feedback_is_contextual_and_does_not_override_sensitive_actions():
    assert screen_feedback(PAYLOAD,'other','Anh/chị mô tả lỗi nhé','Gmail bị lỗi',FACTS) is None
    assert screen_feedback(PAYLOAD,'install_app',CALLER,'Hiển thị Gmail',FACTS) is None
    assert screen_feedback(PAYLOAD,'other',CALLER,'Vâng',FACTS) is None


def test_existing_fixed_and_generated_screen_requests_are_grounded():
    assert 'Tiện ích' in ground_service_line(CALLER,PAYLOAD,FACTS)
    assert validate_line(CALLER,context={'phone_ui':True}) is None
    assert validate_line('Lịch này có đúng với lịch anh/chị đã đặt không?',context={'phone_ui':True})


def test_confirmation_after_mail_guidance_can_finish_the_normal_appointment():
    from app.arena.service_completion import service_completion
    payload={**PAYLOAD,'id':'practice-appointment-ordinary-1','difficulty':'beginner','scenario_kind':'benign'}
    caller=screen_feedback(payload,'other',CALLER,'Hiển thị Gmail',FACTS)
    assert service_completion(payload,'verification','other',caller,'Đúng lịch nhé','comply')
    assert service_completion(payload,'verification','other','Anh/chị tự kiểm tra trước nhé','Vâng','comply') is None
