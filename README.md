# Scam Arena

Bản độc lập tập trung vào module luyện phản xạ qua cuộc gọi lừa đảo giả lập. Giao diện và API được phục vụ cùng origin; Docker Compose đóng gói ứng dụng và dependencies Python.

## Chức năng hiện có

- Chọn kịch bản ngân hàng, giả công an hoặc trúng thưởng; lời thoại được lưu trong `data/scenarios/*.json`.
- Trả lời bằng văn bản hoặc ghi âm tiếng Việt. Faster-Whisper nhận diện lời nói; Piper đọc lời thoại.
- Hội thoại theo script cố định. Một số cụm từ từ chối khiến kịch bản kết thúc sớm.
- Chấm điểm theo một số từ khóa và tốc độ phản hồi. Điểm số chỉ phục vụ luyện tập, không phải đánh giá tâm lý.
- Phiên chơi được giữ ở trình duyệt; server không lưu transcript.

## Chạy bằng Docker Desktop

1. Cài và khởi động Docker Desktop ở chế độ Linux containers.
2. Build image ứng dụng:

   ```powershell
   docker compose build
   ```

3. Tải model Piper vào thư mục `voices/`:

   ```powershell
   docker compose run --rm scam-arena python -m piper.download_voices vi_VN-vais1000-medium --download-dir /app/voices
   ```

4. Khởi động ứng dụng:

   ```powershell
   docker compose up --build
   ```

5. Mở [http://localhost:8000](http://localhost:8000). Kiểm tra API tại [http://localhost:8000/health](http://localhost:8000/health).

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
- Nhận diện ý định và chấm điểm dựa trên luật/từ khóa nên có thể bỏ sót cách diễn đạt hoặc hiểu sai câu phủ định.
- Whisper và Piper chạy cục bộ trong container, cần CPU/RAM và dung lượng lưu model.
- Không có đăng nhập, database hay lưu phiên ở server.
