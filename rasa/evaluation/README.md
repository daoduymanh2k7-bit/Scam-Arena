# Đánh giá Rasa NLU

`heldout.tsv` có 80 câu tiếng Việt mô phỏng, 10 câu cho mỗi nhãn. Trong mỗi nhóm có 7 câu hội thoại và 3 câu mô phỏng văn bản có thể đến từ nhận dạng giọng nói, chẳng hạn thiếu dấu. Các nhãn được đặt trước khi chạy model. Bộ này chưa có bản thu từ micro hay nhãn do người đánh giá độc lập xác nhận.

`evaluate.py` từ chối câu bị trùng trong bộ đánh giá hoặc với bất kỳ câu nào trong `rasa/data`, kể cả sau khi bỏ dấu và dấu câu. Kiểm tra này không phát hiện mọi câu diễn đạt tương đương. Các câu thử nằm ngoài thư mục huấn luyện.

Script dùng cùng bộ câu cho cả hai model và báo cáo độ chính xác, F1 trung bình giữa các nhãn, kết quả theo dạng văn bản và số câu mơ hồ bị đẩy vào một nhãn cụ thể. Nhãn dự phòng của Rasa và dự đoán dưới ngưỡng 0,65 được tính là `unknown`. Đây là đánh giá **riêng Rasa**, nên còn cần đánh giá luồng thực tế có Whisper, luật và LLM nếu muốn đo chất lượng toàn bộ cuộc gọi.

## Chạy lại so sánh

Từ thư mục gốc của dự án, chạy bằng PowerShell:

```powershell
$evaluationMount = "${PWD}:/review:ro"
docker compose run --no-deps --rm -T -v $evaluationMount -e TF_NUM_INTRAOP_THREADS=4 -e TF_NUM_INTEROP_THREADS=2 -e OMP_NUM_THREADS=4 --entrypoint bash rasa -lc 'rasa train nlu --config /review/rasa/evaluation/candidate.yml --nlu /app/data --out /tmp/rasa-candidate --fixed-model-name expanded && python /review/rasa/evaluation/evaluate.py --baseline /app/models --candidate /tmp/rasa-candidate'
```

Bản thử dùng cả `nlu.yml` và `nlu_extra.yml` với 18 epoch, giữ nguyên ngưỡng. Kết quả so sánh hai mô hình thực tế, không tách riêng tác động của dữ liệu và số epoch. Lệnh huấn luyện trong container tạm và không thay model đang phục vụ.

## Kết quả so sánh đầu tiên

| Chỉ số | Model đang chạy | Bản mở rộng |
| --- | ---: | ---: |
| Đúng tổng thể | 52/80 (65,0%) | 52/80 (65,0%) |
| Macro F1 | 64,5% | 64,2% |
| Đúng trên câu hội thoại | 42/56 | 40/56 |
| Đúng trên câu mô phỏng đầu ra nhận dạng | 10/24 | 12/24 |
| Câu mơ hồ bị gán nhãn cụ thể | 8/10 | 8/10 |
| Nhận đúng nhãn chia sẻ dữ liệu | 7/10 | 5/10 |

Bản mở rộng sửa đúng 9 câu mà model cũ sai, đồng thời sai 9 câu mà model cũ đúng. Giữ model đang chạy vì bản thử không tăng độ chính xác chung, không giảm lỗi trên câu mơ hồ và kém hơn trên nhóm chia sẻ dữ liệu.

`rasa/results/intent_report.json` là báo cáo cũ. Các câu sai trong báo cáo đó trùng với dữ liệu huấn luyện hiện tại, nên không dùng số liệu đó làm chuẩn cho câu mới. Khi đã dùng bộ 80 câu này để chọn model, hãy giữ nó làm bộ kiểm tra hồi quy và bổ sung một bộ câu mới do người khác gán nhãn trước khi đánh giá phiên bản tiếp theo.

## Đánh giá Rasa theo ngữ cảnh

`context_heldout.tsv` có 12 câu người gọi, mỗi câu ghép với hai lời đáp ngắn “Được ạ” và “Không ạ”. Script kiểm tra câu hỏi cuối không trùng mẫu huấn luyện sau chuẩn hóa. Hai câu đáp được chấm bằng luật cũ, Rasa ngữ cảnh riêng và luật kết hợp Rasa. Các câu được soạn mô phỏng, có thể gần nghĩa câu huấn luyện và chưa có người gán nhãn độc lập. Đánh giá này không chạy Whisper, LLM hoặc tính điểm.

| Bộ kiểm tra | Trước | Sau |
| --- | ---: | ---: |
| Câu đáp theo ngữ cảnh, luật kết hợp Rasa | 14/24 | 24/24 |
| Câu đứng riêng, Rasa DIET | 52/80 | 55/80 |

Bộ phân loại ngữ cảnh Rasa đứng riêng đạt 24/24 trên bộ câu này. DIET được huấn luyện lại bằng cùng dữ liệu và cấu hình, nên biến động của lần huấn luyện có thể giải thích chênh lệch 3 câu đứng riêng.

Sau khi build image, chạy từ gốc dự án bằng PowerShell:

```powershell
$evaluationMount = "${PWD}:/review:ro"
docker compose run --no-deps --rm -T -v $evaluationMount -e PYTHONPATH=/app:/review/backend -e TF_NUM_INTRAOP_THREADS=4 -e TF_NUM_INTEROP_THREADS=2 --entrypoint python rasa /review/rasa/evaluation/evaluate_context.py
```

## Thử thêm dữ liệu để phân biệt các nhãn dễ nhầm

Tập thử [66 câu bổ sung](training/nlu_contrast.yml) ghép các câu chỉ khác nhau ở một chi tiết quyết định nhãn, như trì hoãn, tự xác minh, làm theo hoặc từ chối. Tập có 3 câu nhắn tin thật từ 2 tài khoản và 63 câu mô phỏng. Các câu mô phỏng bao gồm từ đệm, cách nói vùng miền, câu thiếu dấu và lỗi chép lời giả lập. Không lấy nhãn do hệ thống cũ dự đoán làm đáp án.

PostgreSQL có 4 lượt thoại từ một tài khoản. Giữ riêng tài khoản này cùng toàn bộ bản chép lời của nó khỏi huấn luyện. Loại một mẫu chứa dãy số đã che vì không thể gán nhãn đáng tin cậy từ văn bản còn lại. Các lượt không có tài khoản cũng bị loại khỏi phép tách vì không xác định được chúng có cùng nguồn hay không. Ba mẫu Whisper còn lại đều được gán `unknown`. Tài khoản là đại diện gần đúng cho người nói. Tập này chưa có bản thu gốc hay người gán nhãn độc lập. File cục bộ `.local/speaker_holdout.json` chứa danh sách `training_speakers` và `rows`, với mỗi dòng có `speaker`, `style`, `text` và `intent`. Dùng mã nhóm thay cho định danh tài khoản.

Huấn luyện cả hai bản ở 100 epoch, seed 42 và cùng cấu hình. Chỉ bản thử dùng thêm 66 câu. Tập đánh giá được kiểm tra trùng lặp với dữ liệu huấn luyện sau khi bỏ dấu và dấu câu. Ngưỡng Rasa là 0,65, và phép đo chỉ tính dự đoán của Rasa trên văn bản.

| Chỉ số | Bản gốc huấn luyện lại | Bản thêm 66 câu |
| --- | ---: | ---: |
| Đúng trên tập mô phỏng cố định | 54/80 | 61/80 |
| Macro F1 trên tập mô phỏng | 67,9% | 77,0% |
| Câu `unknown` bị gán nhãn cụ thể | 8/10 | 3/10 |
| Câu không rủi ro bị gán nhãn chia sẻ dữ liệu hoặc chuyển tiền | 3/60 | 1/60 |
| Nhận đúng chia sẻ dữ liệu | 8/10 | 8/10 |
| Nhận đúng chuyển tiền | 10/10 | 10/10 |
| Đúng trên tập Whisper của tài khoản giữ riêng | 2/3 | 1/3 |

Bản thử sửa đúng 10 câu mô phỏng và làm sai thêm 3 câu. Mô hình đang phục vụ đạt 55/80 trên tập mô phỏng và 0/3 trên tập Whisper. Mô hình này được huấn luyện ở lần chạy trước, nên phép so sánh có kiểm soát dùng bản gốc huấn luyện lại ở cùng seed. Giữ bản thử ở chế độ đánh giá vì tác động trên tập Whisper đổi chiều tùy bản đối chiếu. Tập Whisper chưa đủ để đo độ chính xác tổng quát hoặc suy ra tác động cho từng nhãn.

```powershell
$evaluationMount = "${PWD}:/review:ro"
docker compose run --no-deps --rm -T -v $evaluationMount -e TF_NUM_INTRAOP_THREADS=4 -e TF_NUM_INTEROP_THREADS=2 -e OMP_NUM_THREADS=4 --entrypoint bash rasa -lc 'set -e; sed "/epochs: 100/a\    random_seed: 42" /review/rasa/config.yml > /tmp/controlled.yml; mkdir /tmp/contrast-data; cp /review/rasa/data/nlu.yml /review/rasa/evaluation/training/nlu_contrast.yml /tmp/contrast-data/; rasa train nlu --config /tmp/controlled.yml --nlu /review/rasa/data/nlu.yml --out /tmp/base; rasa train nlu --config /tmp/controlled.yml --nlu /tmp/contrast-data --out /tmp/contrast; python /review/rasa/evaluation/evaluate.py --baseline /tmp/base --candidate /tmp/contrast --speaker-holdout /review/rasa/evaluation/.local/speaker_holdout.json'
```

Bỏ đối số `--speaker-holdout` khi chạy trên máy chưa có tập cục bộ.

## Duyệt lượt chơi thật và huấn luyện bản thử

Đăng nhập bằng tài khoản có role `admin`, rồi mở **Quản trị → Duyệt mẫu Rasa** ở ngay dưới thanh đầu trang. Bấm **Lấy mẫu mới** để đọc lượt chơi từ PostgreSQL. Chọn nhóm **Huấn luyện** hoặc **Kiểm thử** cho từng tài khoản, rồi chọn nhãn và bấm **Lưu nhãn** cho từng câu. Mục **Đã xử lý** cho phép sửa nhãn hoặc đưa câu về trạng thái chờ duyệt. **Mô hình kịch bản** mở sơ đồ hội thoại trong cùng thanh Quản trị.

Web lưu quyết định vào cùng workspace với lệnh xuất và huấn luyện phía dưới. Khi dùng Docker Compose, thư mục `.local/review-workflow` được gắn vào ứng dụng và giữ dữ liệu khi container được tạo lại.

Chạy từ thư mục gốc trong PowerShell. Quy trình đọc câu đã che từ PostgreSQL và dùng lại một thư mục cục bộ để các tài khoản có cùng mã qua nhiều lần lấy dữ liệu.

```powershell
$evaluationMount = "${PWD}:/review:ro"
$datasetDir = New-Item -ItemType Directory -Force 'rasa/evaluation/.local/review-workflow'
$datasetMount = "$($datasetDir.FullName):/dataset"

docker compose exec -T scam-arena python /app/rasa/evaluation/dataset_workflow.py --workspace /dataset collect
```

1. Duyệt trên web hoặc mở `.local/review-workflow/review.json`. Trong `speakers`, gán mỗi mã tài khoản đã chọn sang `train` hoặc `holdout`. Giữ toàn bộ lượt của một tài khoản trong một nhóm. Nếu biết nhiều tài khoản thuộc cùng một người, xếp chúng vào cùng nhóm. Chọn nhóm kiểm thử trước khi xem dự đoán. Mã đã dùng trong một đợt xuất được khóa nhóm cho các lần sau.
2. Trong `rows`, kiểm tra từng câu và thay `intent: null` bằng một trong tám nhãn Rasa. Dùng `unknown` khi câu đứng riêng thiếu căn cứ, `skip` nếu muốn loại, hoặc giữ `null` để duyệt sau. Nhãn cũ của hệ thống không được chép sang file duyệt. Bộ lọc loại các câu có chữ số, địa chỉ email, URL nhận diện được hoặc dấu đã che dữ liệu. Người duyệt vẫn cần loại câu có tên, địa chỉ hoặc bí mật viết bằng chữ. Dừng các lệnh lấy dữ liệu khi đang sửa file để tránh ghi đè bản đang mở.
3. Xuất một batch có tên mới, rồi huấn luyện hai bản. Phải có mẫu đã duyệt trong cả hai nhóm. Câu lặp giữa hai nhóm, câu trùng bộ huấn luyện có sẵn hoặc bộ test mô phỏng, và câu có nhãn mâu thuẫn được bỏ trước khi xuất.

```powershell
docker compose run --no-deps --rm -T -v $evaluationMount -v $datasetMount --entrypoint python rasa /review/rasa/evaluation/dataset_workflow.py --workspace /dataset build dot-01
docker compose run --no-deps --rm -T -v $evaluationMount -v $datasetMount -e TF_NUM_INTRAOP_THREADS=4 -e TF_NUM_INTEROP_THREADS=2 -e OMP_NUM_THREADS=4 --entrypoint sh rasa /review/rasa/evaluation/train_reviewed.sh /dataset/dot-01
```

Đọc `dot-01/results/comparison.txt` để so điểm tổng, kết quả theo chế độ, độ bao phủ nhãn và số dự đoán nhầm thành chia sẻ dữ liệu hoặc chuyển tiền. Cả hai bản chạy cùng cấu hình DIET, 100 epoch và seed 42. Chỉ bản thử nhận thêm các câu nhóm `train`. File model, bản chép lời, khóa tạo mã định danh và tập test đều nằm trong thư mục cục bộ đã loại khỏi Git và Docker build. Các lệnh này huấn luyện DIET trên câu đứng riêng và lưu bản thử để xem xét trước khi triển khai. Khi dùng kết quả trên một nhóm giữ riêng để sửa mẫu huấn luyện, hãy lấy nhóm người mới cho lần kiểm thử cuối tiếp theo.
