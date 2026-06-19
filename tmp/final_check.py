"""测试 HTTPS 是否已通，按需重新申请 SSL"""
import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("129.146.23.82", username="root", password="Tsu427173", timeout=15)

def run(cmd, check=False, timeout=60):
    print(f"$ {cmd}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout, get_pty=False)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    code = stdout.channel.recv_exit_status()
    combined = (out+err).strip()
    if combined:
        print(combined)
    if check and code != 0:
        raise RuntimeError(f"exit {code}")
    return out + err

# Test HTTPS via Cloudflare
print("=== Testing HTTPS through Cloudflare ===")
run("curl -sf https://ombre.p0lar1s.uk/ 2>&1 | head -c 300 || echo 'HTTPS failed'")

# Try certbot again now nginx is up
print("\n=== Retry certbot (nginx is now running) ===")
out = run(
    "certbot --nginx -d ombre.p0lar1s.uk --non-interactive --agree-tos "
    "--email admin@p0lar1s.uk --redirect 2>&1",
    timeout=120
)
if "Congratulations" in out or "Certificate not yet due" in out:
    print("SSL certificate issued!")
elif "530" in out or "unauthorized" in out:
    print("\nCertbot still blocked by Cloudflare.")
    print("Since Cloudflare is in front, you have 3 options:")
    print("  1. [Easiest] Cloudflare Dashboard → SSL/TLS → set to 'Flexible'")
    print("     → HTTPS to users will work immediately, no cert needed on VPS")
    print("  2. [Better] Cloudflare Dashboard → SSL/TLS → Origin Server → Create Certificate")
    print("     → Download and deploy on VPS for Full SSL mode")
    print("  3. [Manual] Temporarily disable CF proxy (gray cloud) → run certbot → re-enable")
else:
    print("SSL output:", out[-400:])

print("\n=== Current state ===")
run("docker ps | grep ombre-brain")
run("systemctl is-active nginx")
run("curl -sf http://127.0.0.1:18001/health 2>&1 | head -c 200 || curl -sf http://127.0.0.1:18001/ 2>&1 | head -c 100")

client.close()
