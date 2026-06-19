import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("129.146.23.82", username="root", password="Tsu427173", timeout=15)

_, stdout, stderr = client.exec_command(
    "certbot --nginx -d ombre.p0lar1s.uk --non-interactive --agree-tos "
    "--email admin@p0lar1s.uk --redirect 2>&1",
    timeout=120, get_pty=False
)
out = stdout.read().decode('utf-8', errors='replace')
print(out)
code = stdout.channel.recv_exit_status()
print(f"\nexit code: {code}")
client.close()
