# Triển khai Masterly lên AWS EC2

Masterly chạy trên Ubuntu EC2 với Docker Compose. Nginx nhận HTTP và HTTPS, rồi chuyển tiếp tới Next.js. Next.js xử lý các tuyến `/api`, `/ws` và `/files` tới FastAPI. PostgreSQL 17 dùng pgvector. Docker volumes lưu dữ liệu PostgreSQL và tệp của ứng dụng.

Luồng phát hành là **nhánh chức năng → `dev` → `main` → GHCR → EC2**. Pull request vào `dev` hoặc `main` chạy CI. Khi `main` được cập nhật, GitHub Actions build hai image, đẩy lên GHCR theo commit SHA, rồi dùng AWS Systems Manager (SSM) để triển khai.

## 1. Chuẩn bị repo và GitHub Environment

- [Workflow CI](../.github/workflows/ci.yml) chạy Alembic trên PostgreSQL thử nghiệm, chạy pytest và build Next.js.
- [Workflow phát hành](../.github/workflows/publish-images.yml) build từ [Dockerfile FastAPI](../Dockerfile) và [Dockerfile Next.js](../web/Dockerfile). Job **Deploy to EC2** dùng environment `production`.
- [Compose production](../docker-compose.prod.yml) định nghĩa các dịch vụ và volumes. [Compose release](../deploy/compose.release.yml) chọn hai image từ GHCR thay cho cấu hình build.

Trong repo GitHub, vào **Settings → Environments → New environment**, nhập `production` rồi bấm **Configure environment**. Trong **Deployment branches and tags**, chọn **Selected branches and tags**. Bấm **Add deployment branch or tag rule**, chọn loại **Branch** và nhập `main`. [Cấu hình GitHub Environment](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)

## 2. Tạo EC2 và chuẩn bị thư mục triển khai

1. Trong AWS Console, chọn region `us-east-1`. Tạo EC2 **Ubuntu Server 24.04 LTS**, kiến trúc **x86_64** để chạy image `linux/amd64` mà workflow build. Lưu key pair và ghi lại **Instance ID** cùng **Public IPv4**.
2. Trong Security Group, cho phép inbound TCP `22` từ IP của bạn để SSH, TCP `80` và `443` từ Internet. EC2 cần kết nối HTTPS outbound tới GitHub, GHCR và các endpoint SSM. Compose chỉ publish cổng của Nginx ra host.
3. SSH vào máy và cài Docker Engine kèm Docker Compose plugin bằng mục **Install using the apt repository**. [Cài Docker trên Ubuntu](https://docs.docker.com/engine/install/ubuntu/)

```bash
ssh -i /duong-dan/toi/key.pem "ubuntu@<EC2_PUBLIC_IP>"
```

Sau khi cài Docker, cho user `ubuntu` quyền chạy Docker. Thoát rồi SSH lại để nhận group mới.

```bash
sudo usermod -aG docker ubuntu
```

Chạy các lệnh sau **trên EC2, bằng user `ubuntu`**.

```bash
docker run --rm hello-world
docker compose version

git clone --branch main https://github.com/minhhai205/masterly.git ~/masterly
cd ~/masterly
cp -n deploy/.env.example .env.deploy
chmod 600 .env.deploy
```

Chạy `openssl rand -hex 32` hai lần để lấy hai giá trị riêng cho `DB_PASSWORD` và `AUTH_SECRET`. Tạo `ENCRYPTION_KEY` bằng lệnh dưới. Dùng `nano .env.deploy` để điền ba giá trị và giữ chúng qua các lần deploy.

```bash
openssl rand 32 | openssl base64 -A | tr '/+' '_-'
```

## 3. Trỏ DuckDNS, cấp HTTPS và khởi động PostgreSQL

Trong DuckDNS, trỏ `masterly.duckdns.org` về Public IPv4 của EC2. Nếu IP public đổi, cập nhật bản ghi trước khi kiểm tra HTTPS. Từ máy cá nhân, chạy `nslookup masterly.duckdns.org` và kiểm tra IP trả về.

Trên EC2, khởi động Nginx với cấu hình HTTP để Certbot xác thực tên miền. `--no-deps` cho phép khởi động riêng Nginx. Giữ `MASTERLY_HTTPS_DOMAIN` trống trong `.env.deploy` ở bước cấp chứng chỉ.

```bash
cd ~/masterly
compose() { docker compose --env-file .env.deploy -f docker-compose.prod.yml "$@"; }
domain=masterly.duckdns.org

sudo apt update
sudo apt install -y certbot
sudo install -d -m 0755 /var/www/certbot
sudo install -d -m 0700 /etc/letsencrypt/live /etc/letsencrypt/archive

compose config --quiet
compose up -d --no-deps --wait nginx
sudo certbot certonly --webroot -w /var/www/certbot --cert-name "$domain" -d "$domain"
```

Khi Certbot báo cấp chứng chỉ thành công, mở `.env.deploy` và sửa hai dòng sau.

```dotenv
MASTERLY_HTTPS_DOMAIN=masterly.duckdns.org
COOKIE_SECURE=true
```

Áp dụng cấu hình HTTPS, khởi động PostgreSQL và cài hook để Nginx nạp lại chứng chỉ khi Certbot gia hạn.

```bash
compose run --rm --no-deps nginx nginx -t
compose up -d --no-deps --force-recreate --wait nginx
compose up -d --wait db

sudo install -m 0755 deploy/reload-nginx.sh /etc/letsencrypt/renewal-hooks/deploy/masterly-nginx
sudo systemctl enable --now certbot.timer
sudo certbot renew --dry-run --run-deploy-hooks

compose ps
curl -sS -I "http://$domain/login"
```

Kiểm tra `db` là **healthy**, `nginx` đang chạy và HTTP chuyển hướng `301` về HTTPS. Giữ cổng `80` mở để Certbot gia hạn qua webroot. Backend và web sẽ được khởi động ở lượt deploy đầu tiên. [Certbot webroot và gia hạn](https://eff-certbot.readthedocs.io/en/stable/using.html)

## 4. Kết nối EC2 với AWS Systems Manager

1. Vào **IAM → Roles → Create role**. Chọn **AWS service → EC2**, gắn policy `AmazonSSMManagedInstanceCore` và đặt tên role `MasterlyEc2Ssm`.
2. Vào **EC2 → Instances → chọn instance → Actions → Security → Modify IAM role**, chọn `MasterlyEc2Ssm` rồi lưu. [Gắn IAM role vào EC2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/attach-iam-role.html)
3. Trên Ubuntu EC2, kiểm tra SSM Agent bằng `sudo snap services amazon-ssm-agent`. Nếu Agent chưa có, làm theo hướng dẫn cài đặt rồi kiểm tra lại. [Cài SSM Agent trên Ubuntu](https://docs.aws.amazon.com/systems-manager/latest/userguide/agent-install-ubuntu-64-snap.html)
4. Vào **Systems Manager → Fleet Manager** trong `us-east-1`. Khi instance hiện **Online**, vào **Run Command → Run command**, chọn `AWS-RunShellScript`, chọn đúng instance và chạy `echo ssm-ok`. Kiểm tra lệnh có trạng thái **Success**.

## 5. Cho GitHub Actions quyền gửi lệnh SSM

Trong **IAM → Identity providers**, dùng OIDC provider `token.actions.githubusercontent.com` với audience `sts.amazonaws.com`. Nếu tài khoản chưa có provider này, bấm **Add provider → OpenID Connect**, nhập URL `https://token.actions.githubusercontent.com` và audience `sts.amazonaws.com`. [Cấu hình GitHub OIDC trên AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)

Vào **IAM → Roles → Create role → Custom trust policy**, đặt tên role `MasterlyGitHubDeploy` và dùng trust policy sau. Thay `<AWS_ACCOUNT_ID>` bằng ID tài khoản AWS. Giá trị `sub` dưới đây dùng các ID bất biến của repo `minhhai205/masterly` và environment `production`. [Định dạng OIDC subject](https://docs.github.com/en/actions/reference/security/oidc#immutable-subject-claims)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<AWS_ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:minhhai205@158561042/masterly@1407621113:environment:production"
        }
      }
    }
  ]
}
```

Trong role `MasterlyGitHubDeploy`, vào **Permissions → Add permissions → Create inline policy → JSON**. Dùng policy dưới đây và thay `<AWS_ACCOUNT_ID>`, `<EC2_INSTANCE_ID>` bằng giá trị của bạn. `SendCommand` được giới hạn vào tài liệu `AWS-RunShellScript` và instance Masterly. [Quyền AWS Systems Manager](https://docs.aws.amazon.com/service-authorization/latest/reference/list_ssm.html)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ssm:SendCommand",
      "Resource": [
        "arn:aws:ssm:us-east-1::document/AWS-RunShellScript",
        "arn:aws:ec2:us-east-1:<AWS_ACCOUNT_ID>:instance/<EC2_INSTANCE_ID>"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "ssm:GetCommandInvocation",
      "Resource": "*"
    }
  ]
}
```

Trong GitHub, vào **Settings → Secrets and variables → Actions → Variables** và thêm ba **Repository variables**.

| Tên | Giá trị |
| --- | --- |
| `AWS_DEPLOY_ROLE_ARN` | ARN của role `MasterlyGitHubDeploy` |
| `AWS_REGION` | `us-east-1` |
| `EC2_INSTANCE_ID` | Instance ID của EC2 Masterly, dạng `i-...` |

GitHub Actions tự cấp `GITHUB_TOKEN` để workflow push image lên GHCR. Hai package `masterly-backend` và `masterly-web` cần ở chế độ **Public** để EC2 kéo image ẩn danh. Kiểm tra riêng quyền hiển thị của từng package. [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)

## 6. Deploy lượt đầu qua GitHub Actions

Khi EC2, HTTPS và các quyền đã sẵn sàng, mở PR `dev` → `main`, đợi CI xanh rồi merge. Vào **Actions → Publish Docker images** và mở lượt chạy của commit vừa merge.

> Nếu hai package GHCR chưa từng được tạo, có thể đặt **Required reviewers** cho environment `production` trước khi merge. Khi job `publish` hoàn tất, vào **Package settings** của từng package và chuyển sang **Public**, rồi bấm **Review deployments → Approve and deploy** trong lượt chạy. Sau lượt đầu, bỏ yêu cầu reviewer để các lượt sau tiếp tục tự động. Với hai package Masterly đã public, merge là đủ để kích hoạt cả hai job. [Quản lý quyền hiển thị package](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility)

1. Job **publish** build và push `ghcr.io/minhhai205/masterly-backend:<SHA>` và `ghcr.io/minhhai205/masterly-web:<SHA>`.
2. Job **Deploy to EC2** dùng GitHub OIDC để nhận quyền AWS rồi gửi lệnh SSM. [Script deploy](../deploy/deploy.sh) chạy bằng user `ubuntu` trong `~/masterly`, cập nhật checkout trên `main`, kéo hai image theo SHA, chạy `alembic upgrade head`, rồi khởi động hoặc cập nhật backend và web. Script kiểm tra `/api/auth/status` qua HTTPS trước khi báo thành công.
3. Kiểm tra cả hai job xanh trong **Actions** và bản ghi `production` trong **Deployments**. Mở [trang đăng nhập Masterly](https://masterly.duckdns.org/login) và gọi endpoint kiểm tra qua HTTPS.

```bash
curl -fsS https://masterly.duckdns.org/api/auth/status
```

## 7. Các lần deploy tiếp theo

- PR nhánh chức năng vào `dev`, sau đó PR `dev` vào `main` khi muốn phát hành. Mỗi lần `main` cập nhật, workflow tự build image và chạy migration production trước khi cập nhật backend và web.
- Nếu một bản phát hành cần biến cấu hình mới, thêm giá trị vào `~/masterly/.env.deploy` trên EC2 trước khi merge. Nếu biến mới cần vào container, khai báo nó trong `environment` của dịch vụ tương ứng trong Compose qua PR.
- Nếu có thay đổi cấu hình Nginx hoặc PostgreSQL, áp dụng riêng cho dịch vụ tương ứng trên EC2 sau khi checkout đã cập nhật. Job deploy tự cập nhật hai dịch vụ `backend` và `web`.
- Giữ checkout EC2 ở nhánh `main` và cập nhật mã nguồn qua GitHub. Giữ các volume `db-data` và `app-data` để dữ liệu tồn tại giữa các bản phát hành. `docker compose down -v` xóa các volume của stack.
- Nếu job deploy lỗi, xem bước **Deploy and wait for Run Command** và output của command tương ứng trong **AWS Systems Manager → Run Command → Command history**. Khi đã xử lý nguyên nhân và hai image đã publish, chọn **Re-run failed jobs** để chạy lại job deploy.
