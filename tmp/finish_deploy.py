"""完成 ombre-brain 剩余部署步骤：更换端口、装 nginx、配反代、申请 SSL、启动容器"""
import paramiko, time, sys, io
# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

HOST = "129.146.23.82"
USER = "root"
PASS = "Tsu427173"
DOMAIN = "ombre.p0lar1s.uk"
APP_PORT = 18001
REMOTE_DIR = "/opt/ombre-brain"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASS, timeout=15)
print("Connected.")

def run(cmd, check=True, timeout=300):
    print(f"$ {cmd}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout, get_pty=True)
    out = ""
    for line in iter(stdout.readline, ""):
        print(f"  {line}", end="", flush=True)
        out += line
    code = stdout.channel.recv_exit_status()
    if check and code != 0:
        err = stderr.read().decode()
        raise RuntimeError(f"exit {code}: {err}")
    return out

# ── 1. 更新 docker-compose.yml：用 18001 端口 ──
COMPOSE = f"""services:
  ombre-brain:
    image: ombre-brain:local
    container_name: ombre-brain
    restart: unless-stopped
    ports:
      - "127.0.0.1:{APP_PORT}:8000"
    environment:
      - OMBRE_TRANSPORT=streamable-http
      - OMBRE_BUCKETS_DIR=/data
      - OMBRE_EMBED_BACKEND=api
    volumes:
      - {REMOTE_DIR}/data:/data
      - {REMOTE_DIR}/config.yaml:/app/config.yaml
"""
sftp = client.open_sftp()
with sftp.file(f"{REMOTE_DIR}/docker-compose.yml", "w") as f:
    f.write(COMPOSE)
sftp.close()
print("Updated docker-compose.yml (port 18001).")

# ── 2. 启动容器 ──
run(f"cd {REMOTE_DIR} && docker compose up -d")
time.sleep(4)
run("docker ps | grep ombre-brain")
run(f"curl -sf http://127.0.0.1:{APP_PORT}/ 2>&1 | head -c 200 || echo '(no response yet)'", check=False)

# ── 3. 安装 nginx ──
out = run("nginx -v 2>&1 || echo NONGINX", check=False)
if "NONGINX" in out or "not found" in out:
    print("Installing nginx...")
    run("apt-get update -qq && apt-get install -y nginx")

# ── 4. 配置 nginx 反代 ──
NGINX = f"""server {{
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
        proxy_buffering off;
    }}
}}
"""
sftp = client.open_sftp()
with sftp.file(f"/etc/nginx/sites-available/ombre-brain", "w") as f:
    f.write(NGINX)
sftp.close()
run("ln -sf /etc/nginx/sites-available/ombre-brain /etc/nginx/sites-enabled/ombre-brain")
run("rm -f /etc/nginx/sites-enabled/default", check=False)
run("nginx -t")
run("systemctl enable nginx && systemctl restart nginx")
print("Nginx configured.")

# ── 5. 申请 SSL ──
out = run("certbot --version 2>&1 || echo NOCERT", check=False)
if "NOCERT" in out or "not found" in out:
    run("apt-get install -y certbot python3-certbot-nginx -qq")

print(f"Requesting SSL for {DOMAIN}...")
out = run(
    f"certbot --nginx -d {DOMAIN} --non-interactive --agree-tos "
    f"--email admin@p0lar1s.uk --redirect 2>&1",
    check=False,
    timeout=120,
)
if "Certificate not yet due for renewal" in out or "Congratulations" in out or "Successfully" in out:
    print("SSL OK!")
elif "DNS problem" in out or "Could not" in out:
    print("WARNING: SSL failed (DNS not propagated yet). Run manually later:")
    print(f"  certbot --nginx -d {DOMAIN} --non-interactive --agree-tos --email admin@p0lar1s.uk --redirect")

# ── 6. 最终状态 ──
print("\n=== FINAL STATUS ===")
run("docker ps | grep ombre-brain", check=False)
run(f"curl -sf http://127.0.0.1:{APP_PORT}/ 2>&1 | head -c 300 || echo '(app not responding on port {APP_PORT})'", check=False)
run("systemctl is-active nginx", check=False)
run("certbot certificates 2>&1 | grep -A3 ombre || echo '(no cert yet)'", check=False)
run("docker logs ombre-brain --tail 20 2>&1", check=False)

print(f"\nDone! Access: https://{DOMAIN} (or http if SSL pending)")
client.close()
