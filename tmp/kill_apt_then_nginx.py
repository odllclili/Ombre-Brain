"""强制释放 apt 锁，然后安装 nginx + certbot，配置反代和 SSL"""
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
    if out.strip():
        print(out.strip())
    if err.strip() and check:
        print(f"  stderr: {err.strip()}")
    if check and code != 0:
        raise RuntimeError(f"exit {code}: {err}")
    return out + err

# Kill the stuck apt process
run("kill -9 98373 2>/dev/null || true", check=False)
run("rm -f /var/lib/apt/lists/lock /var/lib/dpkg/lock /var/lib/dpkg/lock-frontend /var/cache/apt/archives/lock", check=False)
run("dpkg --configure -a 2>/dev/null || true", check=False)
time.sleep(2)

# Install nginx + certbot
run("apt-get update -qq")
run("apt-get install -y nginx certbot python3-certbot-nginx")
print("Installed nginx + certbot.")

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
ssl_ok = any(x in out for x in ["Congratulations", "Successfully", "Certificate not yet due"])
if ssl_ok:
    print("SSL issued successfully!")
else:
    print("SSL output:", out[-600:] if len(out) > 600 else out)
    print("SSL may need to be run manually if DNS is not propagated.")

# Final status
print("\n=== FINAL STATUS ===")
run("docker ps | grep ombre", check=False)
run("systemctl is-active nginx", check=False)
run("certbot certificates 2>&1 | grep -E 'Domains|Expiry|VALID' || echo '(no cert)'", check=False)
print(f"\nApp URL: https://{DOMAIN}")
client.close()
