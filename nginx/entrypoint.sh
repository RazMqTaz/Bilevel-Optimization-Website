#!/bin/sh

# Paths for certs
CERT_PATH="/etc/letsencrypt/live/bilevel.me/fullchain.pem"
KEY_PATH="/etc/letsencrypt/live/bilevel.me/privkey.pem"

# If certs don't exist, generate a temporary self-signed cert
if [ ! -f "$CERT_PATH" ] || [ ! -f "$KEY_PATH" ]; then
    echo "Certificates not found, generating temporary self-signed cert..."
    mkdir -p /etc/letsencrypt/live/bilevel.me
    openssl req -x509 -nodes -days 1 -newkey rsa:2048 \
        -keyout "$KEY_PATH" \
        -out "$CERT_PATH" \
        -subj "/CN=localhost"
fi

# Run Nginx in foreground
nginx -g 'daemon off;'
