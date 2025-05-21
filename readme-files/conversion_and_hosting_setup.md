# Convert GeoTiff to mbtiles

```
gdalbuildvrt -a_srs EPSG:2056 lv95.vrt calculated/*.tif
gdalwarp -s_srs EPSG:2056 -t_srs EPSG:3857 -tap -tr 0.5 0.5 -r bilinear -co COMPRESS=DEFLATE -co TILED=YES -co BIGTIFF=YES lv95.vrt webmerc.tif
gdal_translate -of MBTILES webmerc.tif lidar.mbtiles
gdaladdo -r average lidar.mbtiles 2 4 8 16
```

copy lidar.mbtiles to /home/rainer/tilesets

run mbtileserver

goto: [http://localhost:8000/services/lidar/map](http://localhost:8000/services/lidar/map)


# Install on Server

sudo mkdir -p /var/www/lidar
sudo cp /home/you/index.html /var/www/lidar/index.html

nginx-conf:

/etc/nginx/conf.d/lidar.cubetrek.com.conf

```
# ------------------------------------------------------------
# lidar.cubetrek.com  –  static SPA + tile proxy to mbtileserver
# ------------------------------------------------------------

# ➊ HTTPS
server {
    server_name lidar.cubetrek.com;

    # --- security headers -------------------------------------------------
    add_header X-Content-Type-Options  "nosniff"     always;
    add_header X-Frame-Options         "DENY"        always;
    add_header Referrer-Policy         "strict-origin-when-cross-origin" always;
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;

    # --- static site ------------------------------------------------------
    root   /var/www/lidar;
    index  index.html;

    # Single-page app: fall back to /index.html on unknown paths
    location / {
        try_files $uri $uri/ /index.html;
    }

    # --- tile proxy -------------------------------------------------------
    # Everything under /mbtiles/ is handed to the mbtileserver on :8090
    location /mbtiles/ {
        proxy_pass        http://localhost:8090/mbtiles/;
        proxy_set_header  Host              $host;
        proxy_set_header  X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header  X-Forwarded-Proto $scheme;
        # optional: let nginx cache identical tiles for 10 days
        proxy_cache       static_map_cache;
        proxy_cache_valid 200 10d;
        proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
        expires 10d;
        add_header Cache-Control "public, max-age=864000, immutable";
    }

    listen [::]:443 ssl; # managed by Certbot
    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/lidar.cubetrek.com/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/lidar.cubetrek.com/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot

}


server {
    if ($host = lidar.cubetrek.com) {
        return 301 https://$host$request_uri;
    } # managed by Certbot


    listen 80;
    listen [::]:80;
    server_name lidar.cubetrek.com;
    return 404; # managed by Certbot


}
```

# run mbtileserver

Copy mbtileserver to /usr/local/bin/, make sure user mbtiles has access

Create /etc/systemd/system/mbtileserver-lidar.service:

```
[Unit]
Description=Read-only mbtileserver for lidar.cubetrek.com
After=network.target
Wants=network.target

[Service]
Type=simple
User=mbtiles
Group=mbtiles
WorkingDirectory=/home/mbtiles
ExecStart=/usr/local/bin/mbtileserver \
          --host 127.0.0.1 \
          --port 8090 \
          --root-url /mbtiles \
          --tiles-only \
          --disable-preview \
          --disable-tilejson \
          --disable-svc-list \
          lidar.mbtiles

# -------- systemd sandbox hardening -----------------
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=full
ProtectHome=read-only
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
LockPersonality=yes
MemoryMax=256M             # optional resource limits
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target

```