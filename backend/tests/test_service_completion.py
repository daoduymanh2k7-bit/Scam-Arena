import pytest
from app.arena.service_completion import service_completion
from app.arena.line_generator import validate_line


def complete(family, text, *, node='intro', intent='unknown', caller=None, kind='benign', action='other'):
    payload={'id':f'practice-{family}-ordinary-1','family':family,'scenario_kind':kind,'difficulty':'beginner'}
    caller=caller or {'delivery':'Anh/chị muốn nhận ở sảnh hay hẹn lại?',
                      'appointment':'Anh/chị vẫn tiện theo lịch hẹn chứ?',
                      'support':'Anh/chị mô tả lại phần đang gặp lỗi được không?'}[family]
    return service_completion(payload,node,action,caller,text,intent)


@pytest.mark.parametrize('family,text,reason',[
    ('delivery','Ở sảnh đi','delivery_arranged'),
    ('delivery','Nhận tại quầy tiếp nhận nhé','delivery_arranged'),
    ('delivery','Giao lúc 16 giờ nhé','delivery_arranged'),
    ('appointment','Đúng lịch nhé','appointment_confirmed'),
    ('appointment','Vâng','appointment_confirmed'),
    ('appointment','Hẹn 9h30 sáng mai','appointment_confirmed'),
    ('support','Mở ứng dụng là bị thoát.','support_issue_recorded'),
    ('support','Tôi không đăng nhập được ứng dụng.','support_issue_recorded'),
    ('support','Đã hết lỗi rồi.','support_resolved'),
])
def test_service_task_finishes_on_specific_contextual_answer(family,text,reason):
    result=complete(family,text)
    assert result and result.reason==reason and 'kết thúc cuộc gọi' in result.closing


@pytest.mark.parametrize('family,text',[
    ('delivery','Ở sảnh được không?'),('delivery','Để tôi xem đã'),
    ('delivery','Không nhận ở sảnh'),('delivery','Ở sảnh nhưng tôi chưa chắc'),
    ('delivery','Tôi đang nghe máy'),('delivery','Vâng'),
    ('appointment','Chưa tiện theo lịch'),('appointment','Có lẽ đúng lịch'),
    ('support','Tôi không bị lỗi'),('support','Lỗi này sửa thế nào?'),
    ('support','Chưa hết lỗi'),('support','Tôi không chạy bình thường'),
])
def test_questions_and_uncertainty_do_not_finish(family,text):
    assert complete(family,text) is None


def test_completion_never_marks_fraud_or_risky_intents_safe():
    assert complete('delivery','Ở sảnh đi',kind='fraud') is None
    assert complete('delivery','Ở sảnh đi',action='share_sensitive') is None
    assert complete('delivery','Ở sảnh đi',intent='share_sensitive') is None
    assert complete('delivery','Ở sảnh đi',node='verification') is None
    assert complete('delivery','Ở sảnh đi',caller='Anh/chị có đang chờ một việc gì không?') is None


def test_open_conversation_cannot_generate_a_closing_line():
    for line in ['Cảm ơn anh/chị, tôi kết thúc cuộc gọi tại đây.',
                 'Cảm ơn đã xác nhận. Tôi sẽ đặt lịch giao hàng. Xin chờ đợi!',
                 'Vâng, tạm biệt anh/chị.']:
        assert validate_line(line,context={'conversation_ending':False}) is None
    assert validate_line('Anh/chị muốn hẹn nhận ở đâu?',context={'conversation_ending':False})
