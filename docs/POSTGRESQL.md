# PostgreSQL cho Module 2

PostgreSQL là nguồn dữ liệu lúc chạy. Docker volume `postgres-data` giữ kịch bản, luật nhận diện và phiên chơi sau khi container được tạo lại. App tạo/migrate schema và nạp dữ liệu mẫu khi khởi động.

## Các bảng

| Bảng | Chứa gì |
| --- | --- |
| `scenarios` | Danh mục kịch bản: ID số, mã ổn định (`bank`), tên, độ khó, số lượt tối đa, điểm bắt đầu, trạng thái; `payload` chỉ giữ cấu hình phụ như nhân vật, dấu hiệu cảnh báo và bài học. |
| `dialogue_nodes` | Mỗi câu máy nói là một node, có stage, lời nhắc dự phòng, thủ đoạn và node timeout. Mỗi kịch bản có đúng một node bắt đầu và ba node kết thúc. |
| `dialogue_transitions` | Một dòng cho mỗi cặp `(node hiện tại, intent)`, trỏ tới node kế tiếp và chứa thay đổi điểm/phản hồi. |
| `intent_phrase_rules` | Cụm từ bổ sung cho bộ nhận diện. `scenario_id = NULL` nghĩa là dùng chung; nếu có ID thì chỉ dùng cho kịch bản đó. `priority` lớn hơn được xét trước. |
| `intent_defaults` | Luật chung cho `hang_up`, `share_sensitive`, `transfer_money` và `unknown`, tránh lặp nhánh kết thúc ở mọi node. |
| `call_sessions` | Phiên chơi, node hiện tại, điểm, số lượt, trạng thái và kết quả. |
| `call_turns` | Mỗi câu trả lời: node máy vừa nói, ý định, phương pháp nhận diện, điểm/phản hồi và thời gian trả lời. Văn bản người chơi được lưu dưới dạng đã che dãy số dài. |
| `intent_review_candidates` | Câu `unknown` hoặc câu người chơi báo máy hiểu sai, đã che thông tin, ngữ cảnh, đề xuất từ LLM và trạng thái chờ duyệt. Duyệt mới tạo luật hoạt động; từ chối thì không ảnh hưởng bộ nhận diện. |

`scenarios.payload` không còn chứa bản sao của `stages` và `scoring`. Hai phần đó được nạp vào `dialogue_nodes` và `dialogue_transitions`; file JSON trong `data/scenarios/` vẫn là nguồn để tạo kịch bản ban đầu.

## Nạp dữ liệu và cập nhật

Lần đầu chạy, app đọc `data/scenarios/*.json`, tạo metadata, node hội thoại, nhánh và luật chấm. Việc nạp là idempotent: không tạo trùng dữ liệu khi khởi động lại và không ghi đè nội dung đã có trong PostgreSQL. Vì vậy, sửa file JSON của kịch bản đã nạp không tự cập nhật database; cần dùng migration/seed có chủ đích hoặc công cụ quản trị kịch bản ở bước sau.

Các migration schema chạy trong transaction khi app khởi động. Migration chuyển cấu trúc cũ sang các bảng mới và giữ lại nội dung kịch bản, trạng thái, điểm cùng luật ý định hiện có.

## Luồng API

- `POST /api/arena/calls` với `{"scenario_key":"bank"}` tạo phiên và trả node bắt đầu.
- `POST /api/arena/calls/{session_id}/turn` gửi `user_text` và `elapsed_seconds`; server phân loại intent, chọn transition/default, tính điểm và lưu lượt.
- `POST /api/arena/calls/{session_id}/finish` kết thúc thủ công phiên đang mở.
- `GET /api/arena/calls/{session_id}/summary` trả điểm, phản hồi theo lượt, dấu hiệu cảnh báo và bài học.
- `GET /api/arena/history` liệt kê phiên gần đây; `GET /api/arena/calls/{session_id}/transcript` trả hội thoại đã che.
- `POST /api/arena/calls/{session_id}/turns/{turn_no}/flag` đưa lượt người chơi báo hiểu sai vào hàng đợi phân tích.
- `GET /api/arena/admin/intent-candidates` liệt kê câu chờ duyệt. `POST .../{candidate_id}/approve` thêm phrase rule theo kịch bản; `POST .../{candidate_id}/reject` bỏ qua đề xuất.

Nhận diện trong lúc chơi hiện dùng luật trong Python và cụm từ trong database. Khi chưa có luật phù hợp hoặc các luật mâu thuẫn, kết quả là `unknown`; `intent_method` ghi `fallback`. Sau khi kết thúc phiên, các câu `unknown` được đưa vào `intent_review_candidates`; người chơi cũng có thể báo lượt máy phân loại sai từ lịch sử để đưa câu đó vào hàng đợi. Nếu cấu hình `OPENAI_API_KEY`, backend gửi câu đã che số dài/email cùng câu thoại và hành động được yêu cầu tới Responses API để đề xuất ý định/cụm từ. Không có key thì admin có thể gán nhãn thủ công. LLM không được quyền thêm hoặc bật luật; phải duyệt thủ công trong khu vực quản trị trên trang chủ. Compose chỉ bind port trên localhost; cần bổ sung đăng nhập/phân quyền trước khi đưa trang duyệt lên môi trường công khai.

Trước khi lưu câu trả lời, backend thay mọi dãy từ 4 chữ số trở lên bằng `****`. Không lưu bản gốc câu trả lời trong `call_turns`. Thời gian phản hồi được lưu riêng để tính chỉ số tham khảo.

## Xem dữ liệu

```powershell
docker compose exec db psql -U scam_arena -d scam_arena -c "SELECT scenario_id, scenario_name, title, status FROM scenarios ORDER BY scenario_id;"
docker compose exec db psql -U scam_arena -d scam_arena -c "SELECT scenario_id, node_key, stage, is_start, is_terminal FROM dialogue_nodes ORDER BY scenario_id, node_id;"
docker compose exec db psql -U scam_arena -d scam_arena -c "SELECT from_node_id, intent, to_node_id, score_delta FROM dialogue_transitions ORDER BY from_node_id, intent;"
docker compose exec db psql -U scam_arena -d scam_arena -c "SELECT id, scenario_id, intent, phrase, match_type, priority, enabled FROM intent_phrase_rules ORDER BY priority DESC, id;"
docker compose exec db psql -U scam_arena -d scam_arena -c "SELECT session_id, scenario_id, outcome, total_score, turn_no FROM call_sessions ORDER BY started_at DESC;"
docker compose exec db psql -U scam_arena -d scam_arena -c "SELECT session_id, turn_no, user_text_masked, intent, score_delta, feedback FROM call_turns ORDER BY created_at DESC;"
```

## Thêm luật nhận diện

Thêm một dòng vào `intent_phrase_rules` hoặc duyệt một đề xuất ở trang chủ. Cụm dùng `contains` sẽ so khớp sau khi bỏ dấu và chuẩn hóa khoảng trắng; `regex` chạy biểu thức chính quy trên câu đã chuẩn hóa NFC/chữ thường. `phrase_norm` là cụm đã bỏ dấu, chữ thường; hãy cập nhật cột này cùng `phrase` khi sửa luật. Khi duyệt qua UI, cache luật được làm mới tự động. Sau khi sửa trực tiếp bằng SQL, khởi động lại app để xóa cache luật:

```powershell
docker compose restart scam-arena
```

Khu vực duyệt phrase rules trên trang chủ là công cụ nội bộ không có đăng nhập, phù hợp khi chạy local. Không đưa lên máy chủ công khai trước khi có xác thực và phân quyền. Để bật LLM, thêm `OPENAI_API_KEY` vào `.env`, tùy chọn đặt `OPENAI_MODEL`, rồi chạy `docker compose up -d --build scam-arena`. Nếu chưa cấu hình key, câu vẫn được lưu để admin gán nhãn thủ công. Compose mặc định dùng PostgreSQL local; có thể đặt `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` trong `.env` trước lần chạy đầu. Đổi mật khẩu trong `.env` không tự sửa thông tin của volume đã khởi tạo.
