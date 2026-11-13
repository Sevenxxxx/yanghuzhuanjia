# 反向代理：HTTPS + 共享口令 + SSE 不缓冲。
# 安装时由 install-app.sh 把 __DOMAIN__ 换成真实域名。
server {
    listen 80;
    listen [::]:80;
    server_name __DOMAIN__;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name __DOMAIN__;

    # certbot 会自动补全证书配置；这里只是占位
    ssl_certificate     /etc/letsencrypt/live/__DOMAIN__/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/__DOMAIN__/privkey.pem;

    client_max_body_size 60m;   # 图片上传（base64 后更大）
    client_body_timeout 120s;

    location / {
        auth_basic "road maintenance";
        auth_basic_user_file /etc/nginx/road.htpasswd;

        proxy_pass http://127.0.0.1:8095;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 流式回答（SSE）：不缓冲、放宽超时
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 1800s;
        proxy_send_timeout 1800s;
    }

    # 健康检查只给本机，避免对外暴露运行状态
    location = /api/health {
        allow 127.0.0.1;
        deny all;
        proxy_pass http://127.0.0.1:8095;
    }
}
