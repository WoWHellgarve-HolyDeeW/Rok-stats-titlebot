# 🚀 Guia de Deploy - RoK Stats Hub (Windows + XAMPP)

Deploy no servidor Windows com XAMPP (wowhellgarve.com) sem Docker.

---

## 📋 Pré-requisitos no Servidor Windows

### Verificar o que já tens (PowerShell como Admin):

```powershell
# Python (precisa 3.9+)
python --version

# pip
pip --version

# Node.js (só para build)
node --version
npm --version

# Git
git --version
```

### Instalar o que faltar:

| Software | Download |
|----------|----------|
| Python 3.11+ | https://www.python.org/downloads/ |
| Node.js 20 LTS | https://nodejs.org/ |
| Git | https://git-scm.com/download/win |

> ⚠️ Na instalação do Python, marca **"Add to PATH"**

---

## 1️⃣ Configurar Subdomínio DNS

No painel do teu domínio (Cloudflare, GoDaddy, etc.), adiciona:

| Tipo | Nome | Valor | TTL |
|------|------|-------|-----|
| A | stats | [IP do servidor] | Auto |

Resultado: `stats.wowhellgarve.com` → mesmo IP do servidor

---

## 2️⃣ Localização do Projeto

O projeto já está em:
```
C:\Users\admin\Desktop\rok_stats_iara
```

Estrutura:
```
C:\Users\admin\Desktop\rok_stats_iara\    ← código fonte (git)
C:\rokstats\frontend\                      ← frontend compilado (Apache serve)
```

```powershell
# Criar pasta para o frontend compilado
mkdir C:\rokstats\frontend -Force
```

---

## 3️⃣ Setup Backend (FastAPI)

```powershell
cd C:\Users\admin\Desktop\rok_stats_iara\backend

# Criar ambiente virtual
python -m venv .venv

# Ativar venv
.\.venv\Scripts\Activate.ps1

# Instalar dependências
pip install --upgrade pip
pip install -r requirements.txt

# Criar base de dados SQLite
alembic upgrade head

# Testar (Ctrl+C para parar)
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Criar Serviço Windows (corre automaticamente)

#### Opção A: NSSM (Recomendado - mais fácil)

1. Baixa NSSM: https://nssm.cc/download
2. Extrai para `C:\nssm`
3. Executa em PowerShell Admin:

```powershell
# Instalar serviço
C:\nssm\win64\nssm.exe install RokStatsAPI

# Vai abrir uma janela, preenche:
# Path:       C:\Users\admin\Desktop\rok_stats_iara\backend\.venv\Scripts\uvicorn.exe
# Startup:    C:\Users\admin\Desktop\rok_stats_iara\backend
# Arguments:  app.main:app --host 127.0.0.1 --port 8000

# Ou via linha de comando:
C:\nssm\win64\nssm.exe install RokStatsAPI "C:\Users\admin\Desktop\rok_stats_iara\backend\.venv\Scripts\uvicorn.exe" "app.main:app --host 127.0.0.1 --port 8000"
C:\nssm\win64\nssm.exe set RokStatsAPI AppDirectory "C:\Users\admin\Desktop\rok_stats_iara\backend"
C:\nssm\win64\nssm.exe set RokStatsAPI DisplayName "RoK Stats API"
C:\nssm\win64\nssm.exe set RokStatsAPI Start SERVICE_AUTO_START

# Iniciar
C:\nssm\win64\nssm.exe start RokStatsAPI
```

#### Opção B: Script no Startup (mais simples)

Cria `C:\Users\admin\Desktop\rok_stats_iara\start-api.bat`:
```batch
@echo off
cd /d C:\Users\admin\Desktop\rok_stats_iara\backend
call .venv\Scripts\activate.bat
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Adiciona ao Task Scheduler:
1. Abre **Task Scheduler**
2. Create Basic Task → "RokStatsAPI"
3. Trigger: "When the computer starts"
4. Action: Start a program → `C:\Users\admin\Desktop\rok_stats_iara\start-api.bat`
5. Marca "Run whether user is logged on or not"

---

## 4️⃣ Build do Frontend (Estático)

```powershell
cd C:\Users\admin\Desktop\rok_stats_iara\frontend-next

# Instalar dependências
npm install

# Criar ficheiro de configuração
"NEXT_PUBLIC_API_URL=https://stats.wowhellgarve.com/api" | Out-File -Encoding UTF8 .env.production

# Build
npm run build

# Criar pasta para o Apache
mkdir C:\rokstats\frontend -Force

# Copiar ficheiros (depende do output mode)
Copy-Item -Recurse -Force .next\* C:\rokstats\frontend\
Copy-Item -Recurse -Force public\* C:\rokstats\frontend\ -ErrorAction SilentlyContinue
```

### Configurar Next.js para Export Estático

Edita `C:\Users\admin\Desktop\rok_stats_iara\frontend-next\next.config.js`:

```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  trailingSlash: true,
  images: {
    unoptimized: true
  }
}
module.exports = nextConfig
```

Depois rebuild:
```powershell
npm run build
Copy-Item -Recurse -Force out\* C:\rokstats\frontend\
```

---

## 5️⃣ Configurar Apache (XAMPP)

### 5.1 Ativar módulos necessários

Edita `C:\xampp\apache\conf\httpd.conf`:

Descomenta (remove o `#` no início):
```apache
LoadModule proxy_module modules/mod_proxy.so
LoadModule proxy_http_module modules/mod_proxy_http.so
LoadModule rewrite_module modules/mod_rewrite.so
```

### 5.2 Configurar Virtual Host

Edita `C:\xampp\apache\conf\extra\httpd-vhosts.conf`:

```apache
# Site principal (já deves ter algo assim)
<VirtualHost *:80>
    ServerName wowhellgarve.com
    ServerAlias www.wowhellgarve.com
    DocumentRoot "C:/xampp/htdocs"
</VirtualHost>

# RoK Stats (NOVO)
<VirtualHost *:80>
    ServerName stats.wowhellgarve.com
    DocumentRoot "C:/rokstats/frontend"

    <Directory "C:/rokstats/frontend">
        Options -Indexes +FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>

    # Proxy para API Python
    ProxyPreserveHost On
    
    # Redireciona /api/* para o backend Python
    ProxyPass "/api/" "http://127.0.0.1:8000/"
    ProxyPassReverse "/api/" "http://127.0.0.1:8000/"

    # Logs
    ErrorLog "logs/rokstats_error.log"
    CustomLog "logs/rokstats_access.log" common
</VirtualHost>
```

### 5.3 Verificar que vhosts está ativo

Em `C:\xampp\apache\conf\httpd.conf`, confirma que esta linha NÃO tem `#`:
```apache
Include conf/extra/httpd-vhosts.conf
```

### 5.4 Reiniciar Apache

No XAMPP Control Panel: **Stop** → **Start** Apache

Ou em PowerShell Admin:
```powershell
C:\xampp\apache\bin\httpd.exe -k restart
```

---

## 6️⃣ HTTPS com Let's Encrypt (Windows)

### Opção A: Win-ACME (Recomendado)

1. Baixa: https://www.win-acme.com/
2. Extrai para `C:\win-acme`
3. Executa como Admin:

```powershell
cd C:\win-acme
.\wacs.exe
```

4. Escolhe:
   - `N` - Create certificate (default settings)
   - `2` - Manual input
   - Hostname: `stats.wowhellgarve.com`
   - Segue as instruções

### Opção B: Cloudflare (se usares Cloudflare)

Ativa "Full SSL" no Cloudflare - ele trata do HTTPS automaticamente.

---

## 7️⃣ Script de Deploy Automático

Cria `C:\Users\admin\Desktop\rok_stats_iara\deploy.bat`:

```batch
@echo off
echo ====================================
echo    RoK Stats - Deploy Script
echo ====================================

echo.
echo [1/5] Pulling latest changes...
cd /d C:\Users\admin\Desktop\rok_stats_iara
git pull origin main

echo.
echo [2/5] Updating backend dependencies...
cd backend
call .venv\Scripts\activate.bat
pip install -r requirements.txt --quiet
alembic upgrade head

echo.
echo [3/5] Restarting API service...
C:\nssm\win64\nssm.exe restart RokStatsAPI

echo.
echo [4/5] Building frontend...
cd ..\frontend-next
call npm install --silent
call npm run build

echo.
echo [5/5] Deploying frontend files...
xcopy /E /Y /I out\* C:\rokstats\frontend\

echo.
echo ====================================
echo    Deploy complete!
echo    https://stats.wowhellgarve.com
echo ====================================
pause
```

### Usar:
```powershell
# Depois de fazer push no teu PC, no servidor:
C:\Users\admin\Desktop\rok_stats_iara\deploy.bat
```

---

## 8️⃣ Webhook Automático (Opcional)

Cria `C:\xampp\htdocs\webhook-deploy.php`:

```php
<?php
$secret = 'TEU_SECRET_AQUI';
$signature = $_SERVER['HTTP_X_HUB_SIGNATURE_256'] ?? '';
$payload = file_get_contents('php://input');

if (hash_equals('sha256=' . hash_hmac('sha256', $payload, $secret), $signature)) {
    // Executa o deploy em background
    pclose(popen('start /B C:\Users\admin\Desktop\rok_stats_iara\deploy.bat > C:\Users\admin\Desktop\rok_stats_iara\deploy.log 2>&1', 'r'));
    http_response_code(200);
    echo 'Deploy started';
} else {
    http_response_code(403);
    echo 'Invalid signature';
}
```

### No GitHub:
1. **Settings → Webhooks → Add webhook**
2. URL: `https://wowhellgarve.com/webhook-deploy.php`
3. Secret: o mesmo do PHP
4. Events: Just the push event

---

## 🔍 Verificar se está tudo OK

```powershell
# API a correr?
Invoke-WebRequest http://127.0.0.1:8000/health

# Ou no browser:
# http://127.0.0.1:8000/health
# http://127.0.0.1:8000/docs

# Serviço ativo?
C:\nssm\win64\nssm.exe status RokStatsAPI

# Testar config do Apache
C:\xampp\apache\bin\httpd.exe -t

# Ver logs de erro
Get-Content C:\xampp\apache\logs\rokstats_error.log -Tail 50
```

---

## 📁 Estrutura Final no Servidor

```
C:\
├── xampp\
│   ├── htdocs\                                  ← wowhellgarve.com (site principal)
│   └── apache\conf\extra\
│       └── httpd-vhosts.conf                    ← configuração virtual hosts
│
├── Users\admin\Desktop\
│   └── rok_stats_iara\                          ← código fonte (git)
│       ├── backend\
│       │   ├── .venv\
│       │   ├── rokstats.db                      ← base de dados SQLite
│       │   └── ...
│       ├── frontend-next\
│       ├── start-api.bat                        ← arranque da API
│       └── deploy.bat                           ← script de deploy
│
├── rokstats\
│   └── frontend\                                ← stats.wowhellgarve.com (HTML compilado)
│       ├── index.html
│       └── ...
│
└── nssm\                                        ← gestor de serviços
```

---

## 🛠️ Troubleshooting

| Problema | Solução |
|----------|---------|
| API não arranca | Verifica logs: `C:\Users\admin\Desktop\rok_stats_iara\backend\` |
| 502 Bad Gateway | API não está a correr na porta 8000 |
| 503 Service Unavailable | Reinicia o serviço: `nssm restart RokStatsAPI` |
| CORS errors | API já tem `allow_origins=["*"]` ✓ |
| Página em branco | Verifica se `C:\rokstats\frontend\` tem ficheiros |
| Subdomínio não funciona | Verifica DNS + vhosts config |
| Apache não inicia | `httpd.exe -t` para ver erros de config |

---

## 🔄 Workflow Diário

1. **No teu PC:** Desenvolves e testas localmente
2. **Commit + Push:** `git push origin main`
3. **No servidor:** Corre `C:\Users\admin\Desktop\rok_stats_iara\deploy.bat`
4. **Pronto!** Site atualizado em `stats.wowhellgarve.com`

---

## 📞 URLs Finais

| Serviço | URL |
|---------|-----|
| Frontend | https://stats.wowhellgarve.com |
| API | https://stats.wowhellgarve.com/api |
| Health Check | https://stats.wowhellgarve.com/api/health |
| Documentação API | https://stats.wowhellgarve.com/api/docs |

---

## 🔥 Firewall Windows

Se o site não estiver acessível de fora:

```powershell
# Permitir porta 80 (HTTP)
New-NetFirewallRule -DisplayName "Apache HTTP" -Direction Inbound -Port 80 -Protocol TCP -Action Allow

# Permitir porta 443 (HTTPS)
New-NetFirewallRule -DisplayName "Apache HTTPS" -Direction Inbound -Port 443 -Protocol TCP -Action Allow
```

Ou via GUI: **Windows Defender Firewall → Advanced Settings → Inbound Rules → New Rule**
