# Deploy Masterly lên EC2

Chạy từ thư mục gốc của repo trên EC2 đã cài Docker Compose.

```sh
cp -n deploy/.env.example .env.deploy
chmod 600 .env.deploy
```

Điền `DB_PASSWORD` và `AUTH_SECRET` bằng hai giá trị riêng tạo từ `openssl rand -hex 32`.
Tạo `ENCRYPTION_KEY` bằng `openssl rand 32 | openssl base64 -A | tr '/+' '_-'` và giữ khóa này qua các lần deploy.

```sh
compose() { docker compose --env-file .env.deploy -f docker-compose.prod.yml "$@"; }

compose config --quiet &&
compose build backend web &&
compose up -d --wait db &&
compose run --rm --no-deps -T backend alembic upgrade head &&
compose up -d nginx
```

Mở `http://<IP-EC2>/login` và kiểm tra `/api/auth/status`. Nếu lỗi, xem `compose ps` và `compose logs --tail=100`.
Sau khi bật HTTPS cho DuckDNS, đặt `COOKIE_SECURE=true` rồi chạy `compose up -d backend`.
Giữ các volume khi cập nhật app. `compose down -v` sẽ xóa dữ liệu.
