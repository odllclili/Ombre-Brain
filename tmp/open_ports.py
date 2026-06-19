"""开放 80/443 端口，检查 Cloudflare 回源是否通，按需处理 SSL"""
import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("129.146.23.82", username="root", password="Tsu427173", timeout=15)
print("Connected.")

def run(cmd, check=True, timeout=60):
    print(f"$ {cmd}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout, get_pty=False)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    code = stdout.channel.recv_exit_status()
    if (out + err).strip():
        print((out + err).strip())
    if check and code != 0:
        raise RuntimeError(f"exit {code}")
    return out + err

# Show current firewall status
run("ufw status 2>/dev/null || iptables -L INPUT -n --line-numbers 2>/dev/null | head -20 || echo 'no firewall tool found'", check=False)

# Open ports 80 and 443
run("ufw allow 80/tcp 2>/dev/null || true", check=False)
run("ufw allow 443/tcp 2>/dev/null || true", check=False)
run("ufw allow 18001/tcp 2>/dev/null || true", check=False)

# Also open via iptables (OCI default)
run("iptables -I INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null || true", check=False)
run("iptables -I INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || true", check=False)

# Test connectivity from outside
print("\n=== Port test ===")
run("curl -sf http://ombre.p0lar1s.uk/ 2>&1 | head -c 200 || echo 'external access failed'", check=False)

# Check if Cloudflare is in front (bypass CF and hit origin directly)
run("curl -sf --resolve ombre.p0lar1s.uk:80:129.146.23.82 http://ombre.p0lar1s.uk/ 2>&1 | head -c 200 || echo 'direct origin failed'", check=False)

# What is nginx listening on?
run("ss -tlnp | grep :80", check=False)
run("ss -tlnp | grep :18001", check=False)

# Nginx access log
run("tail -5 /var/log/nginx/access.log 2>/dev/null || echo 'no access log'", check=False)
run("tail -10 /var/log/nginx/error.log 2>/dev/null || echo 'no error log'", check=False)

# Direct test on port 18001
run("curl -sf http://127.0.0.1:18001/ 2>&1 | head -c 200", check=False)

print("\n=== Summary ===")
print("Container: running on 127.0.0.1:18001")
print("Nginx: proxy ombre.p0lar1s.uk → 127.0.0.1:18001")
print("Cloudflare 530 means CF can't reach origin.")
print("Check OCI Security List: allow port 80 from 0.0.0.0/0")
print("CF Dashboard: set SSL mode to 'Flexible' if no origin cert")

client.close()
