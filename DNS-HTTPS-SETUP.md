# 🔒 Configuração DNS + HTTPS para RokHellgarve Stats

## 📋 Visão Geral

Para ter HTTPS com o Cloudflare, precisamos:
1. Criar um subdomínio no Cloudflare (ex: `rok.wowhellgarve.com`)
2. Configurar o Apache do XAMPP como reverse proxy
3. Atualizar as portas do frontend

---

## 1️⃣ Configurar DNS no Cloudflare

No painel do Cloudflare para `wowhellgarve.com`:

1. **Clica em "Add record"**
2. **Preenche assim:**
   - **Type:** `A`
   - **Name:** `rok` (vai criar `rok.wowhellgarve.com`)
   - **IPv4 address:** `198.244.176.61`
   - **Proxy status:** ☁️ **Proxied** (laranja) - IMPORTANTE para HTTPS!
   - **TTL:** Auto
3. **Clica "Save"**

> ⚠️ **IMPORTANTE:** O Cloudflare só faz proxy nas portas 80 e 443!
> Por isso precisamos do Apache como reverse proxy.

---

## 2️⃣ Configurar Apache como Reverse Proxy

### Passo 2.1 - Ativar módulos necessários

Edita o ficheiro `C:\xampp\apache\conf\httpd.conf` e descomenta (remove o `#`) estas linhas:

```apache
LoadModule proxy_module modules/mod_proxy.so
LoadModule proxy_http_module modules/mod_proxy_http.so
LoadModule ssl_module modules/mod_ssl.so
```

### Passo 2.2 - Criar Virtual Host

Edita `C:\xampp\apache\conf\extra\httpd-vhosts.conf` e adiciona no final:

```apache
# RokHellgarve Stats - Reverse Proxy
<VirtualHost *:80>
    ServerName rok.wowhellgarve.com
    
    # Proxy para o Frontend (Next.js na porta 3000)
    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:3000/
    ProxyPassReverse / http://127.0.0.1:3000/
    
    # Headers para WebSocket
    RewriteEngine On
    RewriteCond %{HTTP:Upgrade} =websocket [NC]
    RewriteRule /(.*) ws://127.0.0.1:3000/$1 [P,L]
</VirtualHost>

# API Backend - Subdomínio ou path
<VirtualHost *:80>
    ServerName api.wowhellgarve.com
    
    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:8000/
    ProxyPassReverse / http://127.0.0.1:8000/
</VirtualHost>
```

### Passo 2.3 - Verificar configuração

Abre CMD como administrador:
```cmd
cd C:\xampp\apache\bin
httpd -t
```

Se disser "Syntax OK", reinicia o Apache pelo XAMPP Control Panel.

---

## 3️⃣ Adicionar Registo DNS para API (Opcional)

Se quiseres um subdomínio separado para a API:

1. No Cloudflare, adiciona outro registo:
   - **Type:** `A`
   - **Name:** `api` (ou `rokapi`)
   - **IPv4 address:** `198.244.176.61`
   - **Proxy status:** ☁️ Proxied

---

## 4️⃣ Atualizar URL da API no Frontend

No servidor, edita `frontend-next/.env.local`:

```env
NEXT_PUBLIC_API_URL=https://api.wowhellgarve.com
```

Ou se usares o mesmo domínio com path:
```env
NEXT_PUBLIC_API_URL=https://rok.wowhellgarve.com/api
```

Depois reconstrói:
```cmd
cd c:\rok_stats_iara\frontend-next
npm run build
```

---

## 5️⃣ Configuração Cloudflare SSL

No painel Cloudflare:

1. Vai a **SSL/TLS** → **Overview**
2. Escolhe **Flexible** (mais fácil, não precisa de certificado no servidor)
   - O Cloudflare faz HTTPS para o utilizador
   - E HTTP para o teu servidor

> 💡 **Flexible** funciona porque o Cloudflare encripta a conexão até ele, e ele conecta ao teu servidor via HTTP.

---

## 📝 Resumo dos URLs Finais

| Serviço | URL |
|---------|-----|
| Frontend | https://rok.wowhellgarve.com |
| API | https://api.wowhellgarve.com |
| Direto (teste) | http://198.244.176.61:3000 |

---

## 🚀 Checklist Final

- [ ] Registo DNS `rok` criado no Cloudflare
- [ ] Registo DNS `api` criado no Cloudflare (opcional)
- [ ] Módulos Apache ativados (proxy, proxy_http)
- [ ] Virtual Host configurado
- [ ] Apache reiniciado
- [ ] SSL/TLS definido como "Flexible" no Cloudflare
- [ ] `.env.local` atualizado com novo URL da API
- [ ] Frontend reconstruído (`npm run build`)

---

## 🔧 Troubleshooting

### "ERR_TOO_MANY_REDIRECTS"
- No Cloudflare SSL/TLS, muda de "Full" para "Flexible"

### "502 Bad Gateway"
- Verifica se os serviços estão a correr (portas 3000 e 8000)
- Verifica se o Apache tem os módulos proxy ativados

### API não funciona
- Verifica se o CORS no backend aceita o novo domínio
- Edita `backend/app/main.py` e adiciona o domínio à lista de origens permitidas
