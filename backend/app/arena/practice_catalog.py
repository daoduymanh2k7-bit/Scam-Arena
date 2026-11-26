"""Reviewed practice families and bounded case variables. No live personal data."""
import copy
import random

FAMILIES = {
    'delivery': {'label':'Giao hàng', 'context':'Bạn có đơn hàng đã thanh toán, dự kiến giao {window}. Điểm nhận dự kiến: {place}.',
                 'evidence':'Đơn {reference} đã thanh toán. Có thể hẹn nhận tại {place}, {window}. Không có phí thêm hoặc yêu cầu mã đăng nhập.',
                 'official':'Trong ứng dụng mô phỏng: đơn hàng còn hiệu lực; nhận hàng không cần mã đăng nhập.',
                 'intro':'Tôi gọi về đơn hàng giao {window}. Anh/chị muốn nhận ở {place} hay hẹn lại?',
                 'normal':'Đơn đã thanh toán rồi. Tôi chỉ cần thống nhất thời gian và vị trí nhận hàng.',
                 'fraud':'Tôi được báo cần xác nhận thêm trước khi bàn giao. Anh/chị muốn tôi nói rõ bước xác nhận không?',
                 'request':'Anh/chị đọc mã đăng nhập trong tin nhắn để tôi xác nhận giao hàng.', 'action':'share_sensitive'},
    'appointment': {'label':'Đặt lịch', 'context':'Bạn đã đặt lịch bảo trì thiết bị {window} tại {place}; chưa đăng ký dịch vụ khác.',
                    'evidence':'Lịch {reference}: bảo trì {window}, tại {place}. Đổi lịch thực hiện trong ứng dụng; không cần cài phần mềm điều khiển.',
                    'official':'Trong ứng dụng mô phỏng: lịch hẹn còn hiệu lực. Nhân viên chỉ cần xác nhận hoặc đổi giờ.',
                    'intro':'Tôi gọi xác nhận lịch bảo trì {window}. Anh/chị vẫn tiện theo lịch chứ?',
                    'normal':'Nếu giờ đó chưa tiện, mình hẹn lại. Anh/chị cũng có thể tự đổi lịch trong ứng dụng.',
                    'fraud':'Tôi cần làm thêm bước kiểm tra thiết bị trước buổi hẹn. Anh/chị cần tôi giải thích không?',
                    'request':'Anh/chị mở đường dẫn và cài ứng dụng điều khiển để tôi kiểm tra thiết bị trước nhé.', 'action':'install_app'},
    'support': {'label':'Chăm sóc khách hàng', 'context':'Bối cảnh giả định: bạn dùng ứng dụng dịch vụ mô phỏng và gặp lỗi: {support_issue}. Bạn đã gửi phiếu hỗ trợ; chưa yêu cầu đổi mật khẩu hoặc hoàn tiền.',
                'evidence':'Phiếu {reference} ghi nhận: {support_issue}. Phiếu đang chờ kỹ thuật kiểm tra. Hỗ trợ không cần mật khẩu hay mã đăng nhập.',
                'official':'Trung tâm hỗ trợ trong ứng dụng mô phỏng xác nhận có phiếu. Không có quy trình đọc mã đăng nhập cho nhân viên.',
                'intro':'Tôi gọi lại về phiếu {reference}, ghi nhận lỗi: {support_issue}. Hiện vẫn còn tình trạng đó hay đã dùng được bình thường rồi ạ?',
                'normal':'Phiếu đã ghi nhận lỗi này. Anh/chị có muốn bổ sung chi tiết nào, hay để tôi chuyển bộ phận kỹ thuật kiểm tra?',
                'fraud':'Tôi cần đối chiếu tài khoản để tiếp tục xử lý phiếu hỗ trợ. Anh/chị muốn nghe bước tiếp theo không?',
                'request':'Anh/chị đọc mã đăng nhập vừa nhận để tôi truy cập và kiểm tra tài khoản.', 'action':'share_sensitive'},
}


def case_variables(seed):
    rng=random.Random(seed)
    variables={'reference':'DEMO-'+str(rng.randrange(1000,9999)),
            'window':rng.choice(['chiều nay','sáng mai','trong khung giờ đã hẹn']),
            'place':rng.choice(['sảnh tòa nhà','quầy tiếp nhận','điểm hẹn đã ghi trong ứng dụng'])}
    # Appended after existing draws so old reference/window/place seed replay remains stable.
    variables['support_issue']=rng.choice([
        'mục Lịch sử đơn hàng chỉ hiện màn hình trắng, dù trang chủ vẫn mở được',
        'nút Xem lịch hẹn không phản hồi khi bấm, dù các mục khác vẫn dùng được',
        'ứng dụng tự đóng khi mở mục Thông báo, còn trang chủ vẫn hoạt động',
    ])
    return variables


def render(text, variables):
    for key,value in variables.items():
        text=text.replace('{'+key+'}',str(value))
    return text


def case_spec(definition):
    payload=definition['payload']
    spec=FAMILIES[definition['family']].copy()
    spec['context']=payload.get('user_context',spec['context'])
    spec.update(payload.get('case_blueprint') or {})
    return spec


def documents(base):
    """Three families, paired truth classes at every difficulty, distinct graph structures."""
    def node(key,line,action,edges,timeout):
        return {'id':key,'opening_line':line,'objective':'Trả lời trực tiếp và giữ đúng phạm vi tình huống đã khai báo.',
                'tactics':[],'requested_action':action,'max_turns':3,'fallback_lines':[line],
                'transitions':[{'on_intent':i,'next_stage_id':target} for i,target in edges.items()],
                'default_next_stage_id':key,'timeout_next_stage_id':timeout}
    for family,spec in FAMILIES.items():
        for level,difficulty in enumerate(['beginner','intermediate','advanced'],1):
            for benign in [True,False]:
                doc=copy.deepcopy(base)
                doc.update(id=f'practice-{family}-'+('ordinary' if benign else 'impostor')+f'-{level}',version=1,
                           scenario_kind='benign' if benign else 'fraud',family=family,category='other',difficulty=difficulty,
                           title=spec['label']+(' bình thường' if benign else ' giả mạo')+f' — mức {level}',
                           summary='Tình huống mô phỏng để đánh giá bằng chứng và hành động, không suy từ nghề nghiệp.',
                           user_context=spec['context'],start_stage_id='intro',
                           lesson_summary='Kiểm tra trong ứng dụng hoặc kênh độc lập; chỉ hợp tác với yêu cầu đúng phạm vi. Lịch hẹn hoặc phiếu hỗ trợ có thật không làm mọi yêu cầu tiếp theo trở nên hợp lệ.')
                doc['persona']={'name':'Người liên hệ dịch vụ','claimed_role':spec['label'],
                                'speaking_style':['Ngắn gọn, rõ ràng.','Bình tĩnh, giải thích khi được hỏi.','Tự nhiên, đôi khi cần hỏi lại chi tiết; không tự biết thông tin riêng của người nghe.'][level-1],
                                'pressure_level':level}
                doc['case_blueprint']={'evidence':spec['evidence'],'official':spec['official']}
                intro_edges={'unknown':'details','comply':'details','doubt':'details','verify':'verification',
                             'refuse':'END_NEUTRAL' if benign else 'reschedule','hang_up':'END_NEUTRAL'}
                doc['stages']=[node('intro',spec['intro'],'other',intro_edges,'details'),
                               node('verification','Anh/chị có thể tự mở ứng dụng đã dùng trước đó để đối chiếu. Tôi chờ anh/chị kiểm tra.','other',
                                    {'comply':'details','verify':'details','unknown':'details','refuse':'END_NEUTRAL','hang_up':'END_SAFE'},'END_NEUTRAL')]
                if benign:
                    doc['stages'] += [node('details',spec['normal'],'other',
                         {'comply':'confirmation','verify':'verification','refuse':'END_NEUTRAL','hang_up':'END_NEUTRAL','doubt':'verification'},'confirmation'),
                         node('confirmation',('Tôi đã ghi nhận thông tin trong phiếu. Anh/chị đồng ý để tôi chuyển bộ phận kỹ thuật xử lý chứ?' if family=='support' else 'Tôi ghi nhận nội dung vừa trao đổi. Anh/chị muốn tiếp tục theo lịch hay để tôi liên hệ lại?'),'other',
                              {'comply':'END_SAFE','verify':'verification','refuse':'END_NEUTRAL','hang_up':'END_NEUTRAL'},'END_NEUTRAL')]
                    doc['red_flags']=[]
                else:
                    doc['stages'] += [node('details',spec['fraud'],'other',
                         {'comply':'request','doubt':'request','verify':'verification','refuse':'reschedule','hang_up':'END_SAFE'},'request'),
                         node('reschedule','Nếu anh/chị chưa tiện, tôi có thể trao đổi lại. Anh/chị muốn làm rõ lý do liên hệ hay dừng ở đây?','other',
                              {'comply':'details','doubt':'details','verify':'END_SAFE','refuse':'END_SAFE','hang_up':'END_SAFE'},'END_NEUTRAL'),
                         node('request',spec['request'],spec['action'],
                              {'comply':'END_UNSAFE','share_sensitive':'END_UNSAFE','refuse':'END_SAFE','verify':'END_SAFE','hang_up':'END_SAFE','doubt':'verification'},'END_NEUTRAL')]
                    doc['red_flags']=[{'id':'outside-service-scope','stage_id':'request','title':'Yêu cầu vượt phạm vi dịch vụ',
                                       'explanation':'Công việc này không cần mã đăng nhập, quyền điều khiển thiết bị hoặc thông tin xác thực của bạn.','severity':'high'}]
                if level>=2:
                    next(edge for edge in doc['stages'][0]['transitions'] if edge['on_intent']=='doubt')['next_stage_id']='role_check'
                    doc['stages'].append(node('role_check','Tôi liên hệ về công việc đã được nhắc tới. Anh/chị muốn làm rõ nội dung trước hay tự đối chiếu trong ứng dụng?',
                         'other',{'comply':'details','doubt':'details','verify':'verification','refuse':'END_NEUTRAL','hang_up':'END_NEUTRAL'},'verification'))
                if level==3:
                    next(edge for edge in doc['stages'][0]['transitions'] if edge['on_intent']=='unknown')['next_stage_id']='context_check'
                    doc['stages'].append(node('context_check','Tôi nói rõ hơn để tránh nhầm. Anh/chị có đang chờ một việc liên quan đến thông báo này, hay muốn kiểm tra lại trước?',
                         'other',{'comply':'details','doubt':'role_check','verify':'verification','refuse':'END_NEUTRAL','hang_up':'END_NEUTRAL'},'role_check'))
                doc['scoring']={'base_score':60,'rules':[{'intent':i,'points_delta':0,'feedback':'Cần xem hành động cụ thể và bằng chứng trước khi đánh giá.','critical':False}
                                                        for i in ['comply','verify','refuse','hang_up','unknown','doubt']]}
                yield doc
