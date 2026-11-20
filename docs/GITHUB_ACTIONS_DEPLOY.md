# Tự động cập nhật VPS bằng GitHub Actions

Workflow `.github/workflows/deploy.yml` kiểm tra Pull Request và nhánh `main`.
Chỉ push vào `main` hoặc bấm **Run workflow** trên `main` mới triển khai.
Nhánh riêng của collaborator không triển khai. Hai lần triển khai không chạy đồng thời.

## Điều kiện của bản VPS hiện tại

- Ubuntu, đăng nhập SSH `root`, Docker và Docker Compose đã cài.
- Ứng dụng hiện có ở `/opt/scam-arena`, file `.env` nằm tại đó.
- Compose project là `scam-arena`; database hiện có dùng volume
  `scam-arena_postgres-data`. Script chủ động dừng nếu volume khác, tránh tạo nhầm DB rỗng.
- Voice ở `/opt/scam-arena/voices`, tập duyệt ở
  `/opt/scam-arena/rasa/evaluation/.local/review-workflow`.
- Cloudflare Tunnel chạy bằng systemd độc lập với ứng dụng.
- VPS có đủ dung lượng build image Rasa/Python và lưu backup database.

Không cần `git clone` trên VPS: Actions gửi archive chỉ gồm file Git theo dõi.
VPS không cần có quyền truy cập GitHub, nhưng cần Internet để tải image/thư viện.

## 1. Chuẩn bị một lần trên VPS

Những lệnh dưới đây chạy ở terminal **`root@linux31338`**, không phải PowerShell Windows.

Cài công cụ đồng bộ:

```bash
apt-get install -y rsync
```

Tạo thư mục SSH (không thay thế các key đăng nhập đã có):

```bash
install -d -m 700 /root/.ssh
```

Tạo key riêng cho Actions. Nếu file đã tồn tại, không đồng ý ghi đè; dùng key đã có
hoặc chọn một tên mới và điều chỉnh các lệnh tiếp theo.

```bash
ssh-keygen -t ed25519 -C github-actions-scam-arena -f /root/.ssh/github_actions_scam_arena -N ''
```

Thêm public key, tắt forwarding/PTY cho key này. Lệnh vẫn cho phép chạy deploy qua SSH:

```bash
python3 -c 'from pathlib import Path; p=Path("/root/.ssh/authorized_keys"); k="restrict "+Path("/root/.ssh/github_actions_scam_arena.pub").read_text().strip(); old=p.read_text() if p.exists() else ""; p.write_text(old if k in old.splitlines() else old.rstrip()+"\n"+k+"\n")'
```

```bash
chmod 600 /root/.ssh/authorized_keys
```

Key này cấp quyền chạy lệnh root trên VPS cho quy trình triển khai. Chỉ cấp quyền
sửa workflow/repository cho người tin cậy. Nên bảo vệ `main` và duyệt PR trước khi gộp.

## 2. Thêm ba GitHub Actions secrets

Mở repository **Settings → Secrets and variables → Actions → New repository secret**.
Secrets không được đưa vào mã nguồn, issue, chat hoặc ảnh chụp.

| Tên secret | Giá trị |
| --- | --- |
| `VPS_HOST` | `103.69.96.113` |
| `VPS_SSH_KEY` | Toàn bộ private key tạo ở bước 1, gồm cả BEGIN/END và xuống dòng |
| `VPS_KNOWN_HOSTS` | Dòng định danh máy chủ lấy từ lệnh bên dưới |

Lấy private key **chỉ để tự sao chép vào secret**, không gửi cho người khác:

```bash
cat /root/.ssh/github_actions_scam_arena
```

Lấy known hosts trực tiếp trong phiên SSH VPS đã được bạn xác thực:

```bash
awk '{print "103.69.96.113 " $1 " " $2}' /etc/ssh/ssh_host_ed25519_key.pub
```

Sao chép nguyên dòng bắt đầu bằng IP, tiếp theo là `ssh-ed25519` và public key.
Workflow kiểm tra host key nghiêm ngặt, không tự tin tưởng kết quả `ssh-keyscan` trên mạng.
Nếu cài lại OS và đổi host key, cần xác minh lại rồi cập nhật secret này.

Không cần đưa API key LLM hoặc mật khẩu database lên Actions: chúng vẫn ở `.env` VPS.

## 3. Kích hoạt và kiểm tra

Trong GitHub, chọn **Actions → Test and deploy VPS → Run workflow → main**.

Workflow lần đầu có thể đã báo đỏ trước khi secrets được thêm. Thêm xong bấm
**Re-run all jobs** hoặc **Run workflow** để chạy lại.

1. `test`: chạy test backend và quy trình duyệt dữ liệu, kiểm tra cú pháp shell.
2. `deploy`: xác thực SSH, gửi source đúng commit, build image web, Rasa và whisper.cpp trên VPS.
3. Lưu backup DB tại `/opt/scam-arena-backups/`, đồng bộ source, khởi động dịch vụ.
4. Chờ DB, Rasa, ứng dụng healthy rồi kiểm tra `/health` nội bộ.

Nếu job xanh, thử `https://2thub.io.vn`, đăng nhập và gọi thử. Health check chưa
kiểm tra chất lượng giọng nói, micro, LLM hoặc HTTPS bên ngoài.

Sau đó mỗi lần push/merge vào `main` đều chạy quy trình trên. Không cần máy cá nhân mở.
Build dùng cache Docker hiện có; đổi dữ liệu/model Rasa vẫn có thể train lại lâu.
Lần đầu tích hợp whisper.cpp cần biên dịch C++ và tải model lượng tử hóa.
VPS 2 CPU build có thể làm bản đang chạy chậm; khi đổi image có thể gián đoạn ngắn.

## Những gì giữ nguyên và giới hạn

- `.env` và các file `.env.*`, `voices/`, `.git/`, tập dữ liệu duyệt `.local/`
  và dump cũ `deployment/database.dump` được loại khỏi đồng bộ/xóa.
- `.env.example` trên VPS cũng được giữ; mẫu mới vẫn xem được trên GitHub.
- Không chạy `docker compose down`, không xóa volume và không restore DB tự động.
- Source khác trong `/opt/scam-arena` được đồng bộ và có thể bị xóa nếu không có
  trong Git. Không đặt dữ liệu riêng ở các đường dẫn source khác.
- `compose.yaml` được cập nhật theo repo; bản mặc định bind `127.0.0.1:8000`
  phù hợp Cloudflare Tunnel hiện có. Địa chỉ IP công khai cổng 8000 sẽ không còn mở.
- Khi app khởi động, migration/seed hiện có có thể cập nhật DB. Có backup trước
  bước đó nhưng không tự rollback migration. Job lỗi không đồng nghĩa DB chưa đổi.
- Build lỗi thì source và container đang chạy chưa bị thay; lỗi sau bước đồng bộ
  cần kiểm tra log và xử lý. Không có cam kết triển khai không gián đoạn.
- Backup chứa dữ liệu người dùng: thư mục chỉ root truy cập (umask 077).
  Backup và releases chưa tự dọn; theo dõi ổ đĩa và chuyển backup sang nơi riêng khi cần.
- Giữ SSH port 22 truy cập được từ runner GitHub. Không mở cổng database cho Actions.

## Kiểm tra khi có lỗi

Trên VPS:

```bash
df -h /
```

```bash
docker compose -p scam-arena --project-directory /opt/scam-arena ps -a
```

```bash
docker compose -p scam-arena --project-directory /opt/scam-arena logs --tail=60 scam-arena rasa
```

Lỗi thiếu secrets/SSH: kiểm tra ba secrets, public key trong `authorized_keys`,
private key đầy đủ, host key và kết nối port 22. Không tắt host key checking.

## Tài liệu chính thức

- https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets
- https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments
