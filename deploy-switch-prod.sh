#!/bin/bash
# 切换 nginx 代理到 prod 环境 (9091)
set -e

NGINX_CONF="/etc/nginx/sites-available/code-arena"

echo "==> 更新 nginx 配置: 9090 -> 9091"
sudo sed -i 's|proxy_pass http://127.0.0.1:9090;|proxy_pass http://127.0.0.1:9091;|' "$NGINX_CONF"

echo "==> 测试 nginx 配置"
sudo nginx -t

echo "==> 重载 nginx"
sudo nginx -s reload

echo "==> 完成: https://code.cuberqaq.cloud:32020 -> prod (9091)"
