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
Giữ các volume khi cập nhật app. `compose down -v` sẽ xóa dữ liệu.

## Bật HTTPS trên EC2 đang chạy

Trỏ DuckDNS về IP public của EC2, mở cổng `80` và `443` trong Security Group, rồi lấy cấu hình mới từ `main`. Chạy các lệnh sau ở thư mục gốc của repo:

```sh
compose() { docker compose --env-file .env.deploy -f docker-compose.prod.yml "$@"; }
domain=masterly.duckdns.org

git pull --ff-only origin main &&
sudo apt update && sudo apt install -y certbot &&
sudo mkdir -p /var/www/certbot &&
compose run --rm --no-deps nginx nginx -t &&
compose up -d --no-build --no-deps --force-recreate nginx &&
sudo certbot certonly --webroot -w /var/www/certbot --cert-name "$domain" -d "$domain"
```

Khi Certbot cấp chứng chỉ thành công, đặt `MASTERLY_HTTPS_DOMAIN=masterly.duckdns.org` và `COOKIE_SECURE=true` trong `.env.deploy`. Áp dụng bằng image sẵn có:

```sh
compose run --rm --no-deps nginx nginx -t &&
compose up -d --no-build --no-deps --force-recreate nginx &&
compose up -d --no-build --no-deps --wait backend &&
curl -fsS "https://$domain/api/auth/status"
```

Giữ cổng `80` mở để Let's Encrypt gia hạn và cài hook reload Nginx:

```sh
sudo install -m 0755 deploy/reload-nginx.sh /etc/letsencrypt/renewal-hooks/deploy/masterly-nginx
sudo systemctl enable --now certbot.timer
sudo certbot renew --dry-run --run-deploy-hooks
```

## Deploy tự động từ `main`

Sau khi publish hai image lên GHCR, job **Deploy to EC2** dùng GitHub OIDC và
SSM để chạy `deploy/deploy.sh` bằng user `ubuntu` trong `~/masterly`.
Workflow đọc `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION` và `EC2_INSTANCE_ID` từ
Repository variables. EC2 dùng `.env.deploy` và các volume hiện có.

Script pull hai image theo commit SHA, chạy Alembic, cập nhật backend và web,
rồi kiểm tra `/api/auth/status` qua HTTPS. Xem kết quả ở **GitHub → Actions →
Publish Docker images → Deploy to EC2**.
