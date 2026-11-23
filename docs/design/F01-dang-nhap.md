# F01 – Đăng ký và đăng nhập: ghi chú thiết kế

Ghi chú này viết trong lúc làm F01, làm nguyên liệu cho chương 3 (thiết kế). Vì
F01 là phần nền, ghi chú kiêm luôn kiến trúc tổng thể và nền lưu trữ (cơ sở dữ
liệu, lưu tệp, cấu hình triển khai) mà mọi chức năng sau dùng chung. Thiết kế các
bảng nằm ở `docs/design/co-so-du-lieu.md`.

Liên quan đặc tả: mục 2.2.1 (tác nhân Chủ nhóm và Người học), mục 2.3 (tự đăng ký
tài khoản chủ nhóm, phiên có thời hạn, dữ liệu mỗi người tách riêng, giao diện
sáng/tối, hai ngôn ngữ).

## 1. Kiến trúc tổng thể

```text
Trình duyệt
   │  chỉ nói chuyện với địa chỉ của ứng dụng web
   ▼
Ứng dụng web (Next.js)
   ├─ Trang: đăng ký, đăng nhập, trang chủ, hồ sơ, cài đặt
   └─ Proxy: chặn trang khi chưa có phiên; chuyển /api, /ws, /files sang backend
   ▼
Backend (FastAPI)
   ├─ Lớp API: các router, mỗi router một nhóm chức năng
   ├─ Lớp kiểm tra quyền: đọc tài khoản của từng yêu cầu từ cơ sở dữ liệu
   ├─ Lớp dịch vụ: tài khoản, phiên đăng nhập, cài đặt giao diện, cấu hình
   └─ Lớp lưu trữ
        ├─ PostgreSQL (SQLAlchemy, Alembic): dữ liệu nghiệp vụ
        └─ Lớp lưu tệp: thư mục khi phát triển, S3 khi triển khai
```

- Trình duyệt không biết địa chỉ backend; proxy của ứng dụng web chuyển tiếp.
  Nhờ vậy cookie phiên luôn cùng nguồn với trang và không phải mở CORS rộng.
- Mọi đường API trừ đăng ký, đăng nhập, đăng xuất, kiểm tra phiên và đọc cài đặt
  giao diện đều đi qua lớp kiểm tra quyền.
- Cấu hình cần lúc khởi động (kết nối cơ sở dữ liệu, khóa ký phiên, cách lưu tệp)
  đọc từ biến môi trường, khi phát triển nằm trong tệp `.env`.

## 2. Thành phần

| Thành phần | Tầng | Làm gì |
|---|---|---|
| Router đăng nhập | API | Đăng ký, đăng nhập, đăng xuất, kiểm tra phiên; hồ sơ và ảnh đại diện của chính mình |
| Lớp kiểm tra quyền | API | `require_auth` (bắt buộc có phiên), `require_owner` (chỉ chủ nhóm), `optional_auth` (có phiên thì nhận ra người dùng), bản dùng cho WebSocket |
| Dịch vụ tài khoản | Dịch vụ | Tìm tài khoản theo email, kiểm tra đăng nhập, tạo chủ nhóm (kèm nhóm và không gian mặc định), tạo người học, đổi ảnh đại diện và cài đặt giao diện |
| Dịch vụ phiên | Dịch vụ | Băm và kiểm tra mật khẩu (bcrypt), tạo và giải mã phiên (JWT) |
| Ngữ cảnh người dùng | Dịch vụ | Giữ tài khoản của yêu cầu hiện tại; mọi đường dẫn tệp của tài khoản đọc từ đây |
| Router và dịch vụ cài đặt giao diện | API, dịch vụ | Đọc và lưu theme, ngôn ngữ giao diện của từng tài khoản |
| Cơ sở dữ liệu | Lưu trữ | Kết nối bất đồng bộ (`asyncpg`), phiên làm việc cho từng yêu cầu, mô hình 14 bảng, migration |
| Lớp lưu tệp | Lưu trữ | Lưu, đọc, xóa tệp theo khóa; kiểm tra khóa để không ghi ra ngoài vùng lưu |
| Khung web | Web | Bố cục, thanh bên, theme áp dụng trước khi trang hiện, đa ngôn ngữ |

## 3. Dữ liệu

F01 dùng ba bảng của bản thiết kế cơ sở dữ liệu:

| Bảng | Dùng ở F01 |
|---|---|
| `groups` | Một nhóm, tạo khi chủ nhóm đăng ký |
| `accounts` | Email (duy nhất, không phân biệt hoa thường), mật khẩu băm, vai trò `owner` hoặc `learner`, tên hiển thị, ảnh đại diện, theme, ngôn ngữ, trạng thái khóa, ngày tham gia. Mỗi nhóm có đúng một `owner` |
| `workspaces` | Không gian học mặc định, tạo cùng tài khoản |

Ảnh đại diện (cột `avatar`): rỗng là biểu tượng sinh từ tên; `icon:<name>:<color>`
là biểu tượng đã chọn; `img:<version>` là ảnh đã tải lên, tệp nằm ở khóa
`<group_id>/<account_id>/avatar` của lớp lưu tệp, `version` tăng mỗi lần tải để
trình duyệt lấy ảnh mới.

Tệp và biến môi trường:

```text
.env                        biến môi trường khi phát triển (không đưa lên Git)
data/files/                 lớp lưu tệp khi STORAGE_BACKEND=local
data/users/<account_id>/    tệp còn lại của từng tài khoản (thư mục của các chức năng sau)
data/user/settings/         cấu hình dùng chung còn lại (danh mục mô hình cho tới khi
                            chuyển vào bảng groups ở F03)
```

| Biến | Ý nghĩa |
|---|---|
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Kết nối PostgreSQL |
| `AUTH_SECRET` | Khóa ký phiên đăng nhập |
| `SESSION_TTL_HOURS` | Thời hạn phiên (mặc định 24 giờ) |
| `COOKIE_SECURE` | Cookie chỉ gửi qua HTTPS |
| `STORAGE_BACKEND`, `STORAGE_LOCAL_DIR`, `S3_BUCKET`, `AWS_REGION` | Nơi lưu tệp |

## 4. Giao tiếp

| Đường API | Quyền | Vào | Ra |
|---|---|---|---|
| `POST /api/auth/register` | công khai | email, mật khẩu (8 ký tự trở lên), tên hiển thị (tùy chọn) | đặt cookie phiên; mã, email, vai trò. Email đã có: 409 |
| `POST /api/auth/login` | công khai | email, mật khẩu | đặt cookie phiên; mã, email, vai trò. Sai: 401 |
| `POST /api/auth/logout` | công khai | | xóa cookie phiên |
| `GET /api/auth/status` | công khai | cookie phiên (nếu có) | đã đăng nhập chưa, mã, email, tên, vai trò, ảnh |
| `GET /api/auth/profile` | có phiên | | thông tin tài khoản của chính mình |
| `PUT /api/auth/profile` | có phiên | biểu tượng ảnh đại diện | ảnh đại diện mới |
| `PUT, DELETE /api/auth/profile/avatar` | có phiên | tệp ảnh PNG, JPEG, WebP, tối đa 1 MB | ảnh đại diện mới |
| `GET /api/auth/avatar/{user_id}` | có phiên, cùng nhóm | | tệp ảnh |
| `GET /api/settings/ui` | công khai | cookie phiên (nếu có) | theme, ngôn ngữ của tài khoản (hoặc mặc định) |
| `PUT /api/settings/ui` | có phiên | theme và/hoặc ngôn ngữ | cài đặt sau khi lưu |

## 5. Luồng chính

Đăng ký:

1. Người dùng mở trang đăng ký, nhập email, mật khẩu, nhập lại mật khẩu và tên hiển
   thị nếu muốn.
2. Web gửi tới `POST /api/auth/register`. Backend kiểm tra định dạng email, độ dài
   mật khẩu, và email chưa có tài khoản.
3. Trong một giao dịch, dịch vụ tài khoản tạo nhóm, tài khoản chủ nhóm và không gian
   học mặc định.
4. Backend tạo phiên và trả về trong cookie; web chuyển tới trang Nhà cung cấp, vì
   nhóm mới chưa có mô hình nào.

Đăng nhập:

1. Người dùng mở một trang bất kỳ. Proxy thấy chưa có cookie phiên hợp lệ thì
   chuyển sang trang đăng nhập, kèm địa chỉ trang muốn vào.
2. Người dùng nhập email và mật khẩu; web gửi tới `POST /api/auth/login`.
3. Dịch vụ tài khoản tìm tài khoản theo email (không phân biệt hoa thường), kiểm
   tra mật khẩu bằng bcrypt và trạng thái khóa.
4. Đúng thì tạo phiên JWT và trả về trong cookie httpOnly; sai thì trả lỗi 401 và
   trang hiện thông báo.
5. Web quay lại trang người dùng muốn vào.

Mỗi yêu cầu sau khi đăng nhập:

1. Lớp kiểm tra quyền đọc cookie (hoặc header Bearer), kiểm tra chữ ký và hạn của
   phiên, lấy mã tài khoản.
2. Đọc tài khoản từ cơ sở dữ liệu; tài khoản không còn hoặc bị khóa thì coi như
   chưa đăng nhập.
3. Gắn tài khoản vào ngữ cảnh của yêu cầu; dịch vụ đường dẫn đọc ngữ cảnh đó để trả
   về đúng thư mục tệp của tài khoản.

## 6. Quyết định thiết kế

- **Ai cũng tự đăng ký được, và người đăng ký là chủ nhóm.** Mỗi lần đăng ký tạo một
  nhóm mới; chủ nhóm cấu hình mô hình và (ở F02) tạo tài khoản người học cho nhóm.
  Không có tài khoản nào cao hơn chủ nhóm, không xác nhận email.
- **Đăng nhập bằng email**, so khớp không phân biệt hoa thường; email duy nhất trong
  toàn hệ thống, ràng buộc ở cơ sở dữ liệu. Email không tồn tại vẫn mất thời gian
  kiểm tra như sai mật khẩu, để không dò được email nào đã có tài khoản.
- **Phiên là JWT trong cookie httpOnly, chỉ chứa mã tài khoản.** Vai trò và nhóm
  không nằm trong phiên mà đọc lại từ cơ sở dữ liệu ở mỗi yêu cầu, nên khóa hay xóa
  tài khoản có hiệu lực ngay. Proxy của web chỉ xem hạn của phiên để chuyển hướng
  sớm, còn chữ ký luôn do backend kiểm tra.
- **Lớp kiểm tra quyền là hàm bất đồng bộ.** Nếu chạy đồng bộ, FastAPI chạy nó ở
  luồng khác và người dùng gắn vào ngữ cảnh bị mất trước khi tới endpoint; dữ liệu
  sẽ rơi vào nhầm chỗ.
- **Mật khẩu giới hạn 8 ký tự đến 72 byte.** bcrypt chỉ đọc 72 byte đầu, nên mật
  khẩu dài hơn bị từ chối thay vì bị cắt ngầm.
- **Cấu hình khởi động từ biến môi trường.** Khóa ký phiên, kết nối cơ sở dữ liệu
  không nằm trong mã hay cơ sở dữ liệu; trên AWS lấy từ Secrets Manager.
- **Không gian học mặc định từ đầu.** Mọi nội dung đã lưu theo không gian học (mặc
  định); khi có chức năng tạo và chuyển không gian (F05) thì không phải sửa dữ liệu.
- **Ảnh đại diện kiểm tra theo nội dung tệp**, không tin tên tệp hay kiểu tệp do
  trình duyệt gửi; không nhận SVG. Chỉ người cùng nhóm xem được ảnh của nhau.
- **Cài đặt giao diện lưu ở hai nơi**: trình duyệt (để trang hiện đúng theme ngay
  từ đầu, không nhấp nháy) và tài khoản (để mở trên máy khác vẫn giữ). Lựa chọn
  trong trình duyệt được ưu tiên.

## 7. Giao diện

| Màn | Nội dung |
|---|---|
| Đăng ký | Tên hiển thị (không bắt buộc), email, mật khẩu, nhập lại mật khẩu, nút tạo tài khoản; liên kết sang đăng nhập |
| Đăng nhập | Email, mật khẩu, nút đăng nhập; liên kết sang đăng ký |
| Khung chung | Thanh bên: trang chủ; cuối thanh là cài đặt, hồ sơ, đăng xuất; thu gọn được; trên điện thoại là ngăn kéo |
| Trang chủ | Lời chào; chỗ này sau dành cho trò chuyện (F04) và lộ trình (F08) |
| Hồ sơ | Tên hiển thị, email, vai trò (Chủ nhóm hoặc Người học), ngày tham gia; đổi ảnh đại diện bằng ảnh tải lên hoặc biểu tượng và màu; đăng xuất |
| Cài đặt | Chọn theme sáng/tối (có ảnh xem trước); chọn ngôn ngữ giao diện |
