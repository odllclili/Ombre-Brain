"""安装 nginx + certbot，配置反代，申请 SSL"""
import paramiko, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

HOST = "129.146.23.82"
USER = "root"
PASS = "Tsu427173"
DOMAIN = "ombre.p0lar1s.uk"
APP_PORT = 18001

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASS, timeout=15)
print("Connected.")

def run(cmd, check=True, timeout=300):
    print(f"$ {cmd}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout, get_pty=False)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    code = stdout.channel.recv_exit_status()
    if out:
        print(out.strip())
    if err and check:
        print(f"  stderr: {err.strip()}")
    if check and code != 0:
        raise RuntimeError(f"exit {code}")
    return out + err

# Wait for apt lock
print("Waiting for apt lock to release...")
for i in range(30):
    result = run("lsof /var/lib/apt/lists/lock 2>/dev/null | tail -1 || echo FREE", check=False)
    if "FREE" in result or not result.strip():
        print("apt lock released.")
        break
    print(f"  still locked ({i+1}/30), waiting 10s...")
    time.sleep(10)

# Install nginx + certbot
run("apt-get update -qq")
run("apt-get install -y nginx certbot python3-certbot-nginx")
print("nginx + certbot installed.")

# Configure nginx
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
with sftp.file("/etc/nginx/sites-available/ombre-brain", "w") as f:
    f.write(NGINX)
sftp.close()

run("ln -sf /etc/nginx/sites-available/ombre-brain /etc/nginx/sites-enabled/ombre-brain")
run("rm -f /etc/nginx/sites-enabled/default", check=False)
run("nginx -t")
run("systemctl enable nginx && systemctl restart nginx")
print("Nginx running.")

# SSL
print(f"Requesting SSL for {DOMAIN}...")
out = run(
    f"certbot --nginx -d {DOMAIN} --non-interactive --agree-tos "
    f"--email admin@p0lar1s.uk --redirect 2>&1",
    check=False, timeout=120
)
if "Congratulations" in out or "Successfully" in out or "Certificate not yet due" in out:
    print("SSL issued!")
else:
    print("SSL status:", out[-500:] if len(out) > 500 else out)
    print("NOTE: If DNS hasn't propagated, run manually:")
    print(f"  certbot --nginx -d {DOMAIN} --non-interactive --agree-tos --email admin@p0lar1s.uk --redirect")

# Final check
print("\n=== FINAL STATUS ===")
run("docker ps | grep ombre", check=False)
run("systemctl is-active nginx", check=False)
run("certbot certificates 2>&1 | grep -A3 ombre || echo '(no cert)'", check=False)
run(f"curl -sf https://{DOMAIN}/ 2>&1 | head -c 200 || curl -sf http://{DOMAIN}/ 2>&1 | head -c 200", check=False)

print(f"\nDone! https://{DOMAIN}")
client.close()
