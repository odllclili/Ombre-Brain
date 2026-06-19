import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("129.146.23.82", username="root", password="Tsu427173", timeout=15)

def run(cmd):
    _, stdout, stderr = client.exec_command(cmd, timeout=60)
    out = stdout.read().decode()
    err = stderr.read().decode()
    return out + err

print("=== Docker containers ===")
print(run("docker ps -a 2>&1"))
print("=== Build image ===")
print(run("docker images | grep ombre 2>&1"))
print("=== Nginx ===")
print(run("systemctl is-active nginx 2>&1; ls /etc/nginx/sites-enabled/ 2>&1"))
print("=== App health ===")
print(run("curl -sf http://127.0.0.1:8000/ 2>&1 | head -c 300 || echo 'not responding'"))
print("=== Certbot ===")
print(run("certbot certificates 2>&1 | head -15 || echo 'certbot not installed'"))
print("=== Logs ===")
print(run("docker logs ombre-brain --tail 30 2>&1"))

client.close()
