# Deployment & Operations Guide

This guide covers local development, production hosting, reverse proxy configuration, environment variables, and system resource requirements.

---

## 1. System Requirements

* **Operating System**: Windows 10/11, Ubuntu 22.04 LTS+, or Debian 12
* **CPU**: 4+ cores recommended (8+ cores for HydroMT / PySPH model compilation)
* **RAM**: 8 GB minimum (16 GB recommended for large GeoTIFF / mesh processing)
* **Disk Space**: 10 GB free space for datasets, conda environments, and runtime packages
* **Software**:
  * Python 3.11+ (via Miniforge / Conda recommended)
  * Node.js v20+ and npm v10+

---

## 2. Local Environment Setup

### 2.1 Clone Repository & Prepare Raw Datasets
```bash
# Ensure data/raw/data_hidkal/ contains the 6 Hidkal domain files:
# hidkal_dem.tif, hidkal_depth.tif, hidkal_velocity.tif, hidkal_arrival.tif,
# hidkal_assets.geojson, hidkal_roads.graphml
```

### 2.2 Conda Environment Setup
```bash
# Primary Application Environment
conda env create -f environment.yml
conda activate sih-app

# (Optional) Dedicated SPH Environment
conda env create -f environment_pysph.yml

# (Optional) Dedicated HydroMT Environment
conda env create -f environment_hydromt_delft3dfm.yml

# (Optional) Dedicated Google Earth Engine Environment
conda env create -f environment_gee.yml
```

### 2.3 Frontend Dependencies Setup
```bash
cd frontend
npm install
cd ..
```

### 2.4 One-Command Automated Verification & Demo Launch
```powershell
# Run full 79-test suite and frontend production build
.\scripts\verify.ps1

# Start backend & frontend demo session safely
.\scripts\demo.ps1
```

---

## 3. Production Deployment Architecture

```
Internet / End Users
        │
        ▼ (Port 80/443 HTTPS)
┌───────────────────────────────┐
│ NGINX / Caddy Reverse Proxy   │
│ - SSL / TLS Termination       │
│ - GZip & Static File Caching  │
│ - Rate Limiting               │
└──────┬─────────────────┬──────┘
       │                 │
       ▼ (/api/*)        ▼ (/* static assets)
┌──────────────┐   ┌───────────────────────┐
│ FastAPI App  │   │ Frontend Production   │
│ (Uvicorn)    │   │ (dist/ HTML/JS/CSS)   │
│ Port 8000    │   │                       │
└──────┬───────┘   └───────────────────────┘
       │
 ┌─────┴─────────────────────────┐
 │ Read-Only Data: data/raw/     │
 │ Persistent Store: data/runtime│
 └───────────────────────────────┘
```

### 3.1 Environment Configuration (`.env`)
Create a `.env` file in the project root:
```env
CORS_ORIGINS=https://dambreak.mygov.in,https://dambreak-admin.mygov.in
SIH_RUNTIME_DIR=/var/lib/sih-runtime
ENABLE_DFLOWFM_EXECUTION=false
DFLOWFM_EXECUTABLE=/opt/delft3dfm/bin/dflowfm
ENABLE_PYSPH_EXECUTION=false
PYSPH_PYTHON_PATH=/opt/conda/envs/sih-pysph/bin/python
ENABLE_GEE_TASKS=false
GEE_PROJECT_ID=my-dam-hazard-project
```

### 3.2 Production NGINX Reverse Proxy Configuration
```nginx
server {
    listen 80;
    server_name dambreak.mygov.in;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name dambreak.mygov.in;

    ssl_certificate /etc/letsencrypt/live/dambreak.mygov.in/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/dambreak.mygov.in/privkey.pem;

    # Frontend Static Files
    root /app/frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # API Backend Reverse Proxy
    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # GZip & Cache Headers
        proxy_buffering on;
        proxy_read_timeout 60s;
    }

    # Tile Caching
    location /api/rasters/ {
        proxy_pass http://127.0.0.1:8000/api/rasters/;
        proxy_cache_valid 200 1h;
        expires 1h;
        add_header Cache-Control "public, no-transform";
    }
}
```

### 3.3 Systemd Service Configuration (Linux)
`/etc/systemd/system/sih-backend.service`:
```ini
[Unit]
Description=SIH Dam Break Decision Support System API
After=network.target

[Service]
Type=simple
User=sihapp
Group=sihapp
WorkingDirectory=/app/backend
EnvironmentFile=/app/.env
ExecStart=/opt/conda/envs/sih-app/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
