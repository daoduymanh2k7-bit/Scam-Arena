# Scam Arena

Bản độc lập tập trung vào module luyện phản xạ qua cuộc gọi lừa đảo giả lập. Giao diện và API được phục vụ cùng origin; Docker Compose đóng gói ứng dụng và dependencies Python.

## Chức năng hiện có

- Chọn kịch bản ngân hàng, giả công an hoặc trúng thưởng; PostgreSQL lưu node hội thoại, nhánh và luật nhận diện.
- Trả lời bằng văn bản hoặc ghi âm tiếng Việt. Faster-Whisper nhận diện lời nói; Piper đọc lời thoại.
- Hội thoại chạy theo các bảng `dialogue_nodes` và `dialogue_transitions`; câu trả lời chọn nhánh theo một trong 8 ý định.
- Điểm và phản hồi được gắn với transition/default của ý định; phần tổng kết lấy kết quả đã lưu trong PostgreSQL.
- `call_sessions` và `call_turns` lưu phiên chơi. Câu trả lời được che dãy số từ 4 chữ số trở lên trước khi lưu.
- Trang chủ có lịch sử xem lại hội thoại và hàng đợi duyệt câu `unknown`; LLM chỉ đề xuất, admin duyệt mới thêm luật.

## Chạy bằng Docker Desktop

1. Cài và khởi động Docker Desktop ở chế độ Linux containers.
2. Tùy chỉnh thông tin PostgreSQL trong `.env` (có thể sao chép từ `.env.example`). Giá trị mặc định chỉ dành cho máy local.
3. Build image ứng dụng:

   ```powershell
   docker compose build
   ```

4. Tải model Piper vào thư mục `voices/`:

   ```powershell
   docker compose run --rm scam-arena python -m piper.download_voices vi_VN-vais1000-medium --download-dir /app/voices
   ```

5. Khởi động ứng dụng và PostgreSQL:

   ```powershell
   docker compose up --build
   ```

6. Mở [http://localhost:8000](http://localhost:8000). Kiểm tra API tại [http://localhost:8000/health](http://localhost:8000/health).

Khi PostgreSQL khởi động lần đầu, ứng dụng chuyển kịch bản từ `data/scenarios/*.json` thành metadata, dialogue nodes và transitions, rồi nạp mẫu câu từ `data/intent_phrases.json`. Sau đó PostgreSQL là nguồn dữ liệu lúc chạy; dữ liệu được giữ trong Docker volume `postgres-data` khi tạo lại container. Xem schema, API phiên chơi và lệnh xem dữ liệu trong [`docs/POSTGRESQL.md`](docs/POSTGRESQL.md).

## Xem sơ đồ nhánh kịch bản

Sơ đồ được tạo từ `data/scenarios/*.json`. Không cần cài Mermaid. Chạy lệnh sau bằng Python 3.11 trở lên để tạo/cập nhật trang HTML:

```powershell
python backend/app/scenario_visualizer.py
```

Mở `frontend/static/scenario-map.html` trực tiếp trong trình duyệt, hoặc khởi động ứng dụng Docker rồi vào [http://localhost:8000/scenario-map.html](http://localhost:8000/scenario-map.html). Có thể lọc theo kịch bản/giai đoạn, tải SVG hoặc sao chép mã Mermaid. Trang cần Internet để tải thư viện Mermaid từ CDN. Ứng dụng cũng tự tạo lại sơ đồ khi khởi động.

Lần đầu nhận diện giọng nói, Faster-Whisper tải model `base` về Docker volume `whisper-cache`; lần tải đầu cần Internet và có thể mất thời gian. Volume giữ model sau khi container được tạo lại. Đổi model bằng biến môi trường `WHISPER_MODEL`. Nhận diện chạy trên CPU với `int8` để giới hạn RAM và tránh đưa CUDA/PyTorch vào image. [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) dùng CTranslate2 và PyAV; không cần cài FFmpeg hệ thống.

Micro thường được trình duyệt cho phép trên `localhost`. Nếu mở ứng dụng qua một máy chủ khác, cần dùng HTTPS và cấp quyền micro. Có thể nhập câu trả lời bằng bàn phím nếu không muốn dùng micro.

## Chạy không dùng Docker

Cần Python 3.12+ và model Piper trong `voices/`.

```powershell
py -3.12 -m venv .venv
\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m piper.download_voices vi_VN-vais1000-medium --download-dir voices
python -m uvicorn app.main:app --app-dir backend --reload
```

Mở `http://127.0.0.1:8000`.

## Cấu trúc

```text
backend/app/
├── api/                 # HTTP endpoints
├── arena/               # kịch bản, hội thoại, nhận diện ý định, chấm điểm
├── voice/               # Whisper và Piper
├── main.py
└── schemas.py
data/scenarios/          # nguồn kịch bản JSON duy nhất
frontend/static/         # giao diện Scam Arena
Dockerfile
compose.yaml
```

## Giới hạn

- Kẻ lừa đảo dùng lời thoại cố định, chưa phản ứng tự nhiên như LLM.
- Nhận diện trong lúc chơi ưu tiên Rasa NLU (8 nhãn tiếng Việt); các luật tất định cho hành vi nguy hiểm được chạy trước, còn luật cụm từ trong PostgreSQL là phương án dự phòng khi Rasa không sẵn sàng hoặc độ tin cậy thấp. Rasa chỉ phân loại ý định; engine hiện tại vẫn chọn nhánh và chấm điểm. LLM chỉ phân tích sau phiên nếu cấu hình `OPENAI_API_KEY`.
- Whisper và Piper chạy cục bộ trong container, cần CPU/RAM và dung lượng lưu model.
- Rasa Open Source chạy trong container riêng, được build từ `rasa/data/nlu.yml`; sau khi sửa ví dụ huấn luyện cần build lại image bằng `docker compose up -d --build rasa scam-arena`. Lần build đầu tải image Rasa lớn (khoảng 1.2 GB) và train mô hình.
- Bộ dữ liệu ban đầu có 320 câu đã gán nhãn cân bằng (40 câu cho mỗi intent), gồm câu đủ chủ ngữ, câu nói tắt/không chủ ngữ và một số câu không dấu. Đây là dữ liệu khởi đầu, chưa phải độ chính xác đã được đo; cần tiếp tục bổ sung câu thật đã rà nhãn và đánh giá nhầm lẫn trước khi dùng công khai.
- Chưa có giao diện admin để chỉnh nội dung kịch bản; phrase rules có thể được thêm sau khi duyệt đề xuất trên trang chủ hoặc cập nhật qua PostgreSQL.
- Chưa có đăng nhập; `user_id` trong phiên chơi để trống.
- Khu vực duyệt nội bộ chỉ phù hợp với bản local hiện bind vào `127.0.0.1`; cần thêm đăng nhập và phân quyền trước khi công khai.
