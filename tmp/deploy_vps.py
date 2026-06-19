"""
Ombre Brain VPS 部署脚本
- 上传项目文件
- 在 VPS 上构建 Docker 镜像
- 配置 Nginx 反代 + 启动服务
"""

import os
import sys
import time
import tarfile
import tempfile
import paramiko
from pathlib import Path

HOST = "129.146.23.82"
USER = "root"
PASS = "Tsu427173"
DOMAIN = "ombre.p0lar1s.uk"
REMOTE_DIR = "/opt/ombre-brain"
APP_PORT = 8000

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # P:\OB\OB-Test

# Files/dirs to include in the tarball
INCLUDE = [
    "src",
    "frontend",
    "requirements.txt",
    "Dockerfile",
    "VERSION",
    "config.example.yaml",
]


def log(msg):
    print(f"[deploy] {msg}", flush=True)


def make_tarball() -> str:
    """打包项目文件为 tar.gz，返回临时文件路径。"""
    tmp = tempfile.mktemp(suffix=".tar.gz")
    log(f"Packing project → {tmp}")
    with tarfile.open(tmp, "w:gz") as tar:
        for item in INCLUDE:
            src = PROJECT_ROOT / item
            if src.exists():
                tar.add(str(src), arcname=item)
                log(f"  + {item}")
            else:
                log(f"  ! skipped (not found): {item}")
    return tmp


def ssh_connect() -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    log(f"Connecting to {HOST}...")
    client.connect(HOST, username=USER, password=PASS, timeout=15)
    log("Connected.")
    return client


def run(client: paramiko.SSHClient, cmd: str, check=True) -> str:
    log(f"$ {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=300, get_pty=True)
    out = ""
    for line in iter(stdout.readline, ""):
        print(f"  {line}", end="", flush=True)
        out += line
    exit_code = stdout.channel.recv_exit_status()
    if check and exit_code != 0:
        err = stderr.read().decode()
        raise RuntimeError(f"Command failed (exit {exit_code}): {cmd}\n{err}")
    return out


def upload_tarball(client: paramiko.SSHClient, local_path: str):
    log(f"Uploading tarball...")
    sftp = client.open_sftp()
    remote_path = f"/tmp/ombre-brain-deploy.tar.gz"
    sftp.put(local_path, remote_path)
    sftp.close()
    log(f"Uploaded → {remote_path}")
    return remote_path


def upload_config(client: paramiko.SSHClient):
    """上传 config.yaml（不设置 API key，embedding 禁用）。"""
    config_content = """transport: "streamable-http"
log_level: "INFO"

merge_threshold: 75

dehydration:
  model: "deepseek-chat"
  base_url: "https://api.deepseek.com/v1"
  max_tokens: 1024
  temperature: 0.1

decay:
  lambda: 0.05
  threshold: 0.3
  check_interval_hours: 24
  emotion_weights:
    base: 1.0
    arousal_boost: 0.8

embedding:
  enabled: false

scoring_weights:
  topic_relevance: 4.0
  emotion_resonance: 2.0
  time_proximity: 1.5
  importance: 1.0

matching:
  fuzzy_threshold: 50
  max_results: 5

surfacing:
  breath_max_results: 20
  breath_max_tokens: 10000
  feel_max_tokens: 6000
  sampling:
    enabled: false

limits:
  max_bucket_bytes: 51200
  max_pinned: 20

bucket_type_defaults:
  letter:
    weight: 1.0
    dont_surface: false
  plan:
    weight: 0.5

wikilink:
  enabled: true
  use_tags: false
  use_domain: true
  use_auto_keywords: true
  auto_top_k: 4
  min_keyword_len: 3
  exclude_keywords: []
"""
    sftp = client.open_sftp()
    with sftp.file(f"{REMOTE_DIR}/config.yaml", "w") as f:
        f.write(config_content)
    sftp.close()
    log("Config uploaded.")


NGINX_CONF = f"""server {{
    listen 80;
    server_name {DOMAIN};

    location / {{
        proxy_pass http://127.0.0.1:{APP_PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }}
}}
"""

DOCKER_COMPOSE = f"""services:
  ombre-brain:
    build:
      context: .
      dockerfile: Dockerfile
    image: ombre-brain:local
    container_name: ombre-brain
    restart: unless-stopped
    ports:
      - "127.0.0.1:{APP_PORT}:{APP_PORT}"
    environment:
      - OMBRE_TRANSPORT=streamable-http
      - OMBRE_BUCKETS_DIR=/data
      - OMBRE_EMBED_BACKEND=api
    volumes:
      - /opt/ombre-brain/data:/data
      - /opt/ombre-brain/config.yaml:/app/config.yaml
"""


def deploy():
    # 1. Pack
    tarball = make_tarball()

    # 2. Connect
    client = ssh_connect()

    try:
        # 3. Install Docker if missing
        out = run(client, "docker --version 2>/dev/null || echo 'NODOCK'", check=False)
        if "NODOCK" in out or "not found" in out:
            log("Installing Docker...")
            run(client, "curl -fsSL https://get.docker.com | sh")
            run(client, "systemctl enable docker && systemctl start docker")
        else:
            log("Docker already installed.")

        # 4. Prepare remote dir
        run(client, f"mkdir -p {REMOTE_DIR}/data")

        # 5. Upload tarball
        remote_tar = upload_tarball(client, tarball)
        run(client, f"tar -xzf {remote_tar} -C {REMOTE_DIR} && rm {remote_tar}")

        # 6. Upload docker-compose.yml + config
        sftp = client.open_sftp()
        with sftp.file(f"{REMOTE_DIR}/docker-compose.yml", "w") as f:
            f.write(DOCKER_COMPOSE)
        sftp.close()
        upload_config(client)

        # 7. Build & start Docker
        run(client, f"cd {REMOTE_DIR} && docker compose build --no-cache")
        run(client, f"cd {REMOTE_DIR} && docker compose up -d")

        # 8. Setup Nginx
        out = run(client, "nginx -v 2>&1 || echo 'NONGINX'", check=False)
        if "NONGINX" in out:
            log("Installing Nginx...")
            run(client, "apt-get update -qq && apt-get install -y nginx")

        sftp = client.open_sftp()
        with sftp.file(f"/etc/nginx/sites-available/ombre-brain", "w") as f:
            f.write(NGINX_CONF)
        sftp.close()

        run(client, "ln -sf /etc/nginx/sites-available/ombre-brain /etc/nginx/sites-enabled/ombre-brain")
        run(client, "rm -f /etc/nginx/sites-enabled/default", check=False)
        run(client, "nginx -t && systemctl reload nginx")

        # 9. SSL with certbot
        out = run(client, "certbot --version 2>/dev/null || echo 'NOCERT'", check=False)
        if "NOCERT" in out:
            log("Installing certbot...")
            run(client, "apt-get install -y certbot python3-certbot-nginx -qq")

        log("Requesting SSL certificate...")
        run(client,
            f"certbot --nginx -d {DOMAIN} --non-interactive --agree-tos "
            f"--email admin@{DOMAIN} --redirect",
            check=False  # may fail if DNS not propagated yet
        )

        # 10. Check container health
        time.sleep(3)
        run(client, "docker ps | grep ombre-brain")
        run(client, f"curl -sf http://127.0.0.1:{APP_PORT}/health || curl -sf http://127.0.0.1:{APP_PORT}/ | head -c 200")

        log("=" * 50)
        log(f"Deployment complete!")
        log(f"HTTP:  http://{DOMAIN}")
        log(f"HTTPS: https://{DOMAIN}")
        log(f"Container logs: docker logs ombre-brain -f")
        log("=" * 50)

    finally:
        client.close()
        os.unlink(tarball)


if __name__ == "__main__":
    deploy()
