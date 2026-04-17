#  ROK Protocol Analysis - Guia Prático

## Pré-requisitos

### 1. Software Necessário
- Python 3.9+
- BlueStacks 5 (ou outro emulador Android)
- ADB (Android Debug Bridge)

### 2. Instalar Dependências Python
```powershell
pip install mitmproxy frida-tools msgpack blackboxprotobuf
```

---

## Opção A: Interceção com mitmproxy (Recomendado para começar)

### Passo 1: Instalar Certificado CA no Android

1. **Iniciar mitmproxy** para gerar certificado:
   ```powershell
   mitmproxy
   ```
   (Fechar depois de iniciar)

2. **Localizar certificado:**
   ```
   %USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.cer
   ```

3. **Instalar no BlueStacks:**
   - Copiar certificado para pasta partilhada
   - No BlueStacks: Settings → Security → Install from storage
   - Selecionar o certificado

### Passo 2: Configurar Proxy no BlueStacks

1. **Descobrir IP da máquina:**
   ```powershell
   ipconfig | Select-String IPv4
   ```

2. **Configurar no BlueStacks:**
   - Settings → Network → Proxy
   - Server: `<IP_DA_MAQUINA>`
   - Port: `8080`

### Passo 3: Capturar Tráfego

```powershell
cd RESEARCH
mitmdump -s mitmproxy_addons/rok_interceptor.py
```

4. **No BlueStacks:** Abrir RoK e navegar pelos rankings

5. **Verificar pasta `captured_rok_data/`** para ficheiros capturados

---

## Opção B: Bypass SSL Pinning com Frida

### Quando Usar?
Se mitmproxy mostrar erros SSL/TLS mesmo com certificado instalado, o app usa **SSL pinning**.

### Passo 1: Preparar Frida Server

1. **Verificar arquitectura do emulador:**
   ```powershell
   adb shell getprop ro.product.cpu.abi
   ```
   (Normalmente `x86_64` para BlueStacks)

2. **Download frida-server:**
   - https://github.com/frida/frida/releases
   - Ficheiro: `frida-server-<version>-android-x86_64.xz`

3. **Instalar no emulador:**
   ```powershell
   # Extrair o .xz primeiro
   adb push frida-server /data/local/tmp/
   adb shell chmod 755 /data/local/tmp/frida-server
   adb shell su -c "/data/local/tmp/frida-server &"
   ```

### Passo 2: Executar Script SSL Bypass

```powershell
# Listar apps
frida-ps -U | Select-String -i lilith

# Executar bypass (substituir com nome do pacote correto)
frida -U -f com.lilithgame.roc.gp -l frida_scripts/ssl_bypass.js
```

### Passo 3: Combinar com mitmproxy

Com Frida a fazer bypass, mitmproxy conseguirá capturar tráfego HTTPS.

---

## Analisar Dados Capturados

### Usar o Analisador

```powershell
cd RESEARCH

# Analisar um ficheiro
python analyze_payload.py captured_rok_data/some_file.bin

# Analisar toda a pasta
python analyze_payload.py captured_rok_data/
```

### O que Procurar

1. **Endpoints de Rankings:**
   - Lista de governadores com power, kills, etc.
   - Estrutura de dados (JSON/Protobuf/MessagePack)

2. **IDs e Parâmetros:**
   - Kingdom IDs
   - Player/Governor IDs
   - Parâmetros de request (paginação, filtros)

3. **Autenticação:**
   - Tokens, cookies, headers especiais
   - Como são gerados/renovados

---

## Interpretar Resultados

### Cenário 1: JSON Limpo
```json
{
  "players": [
    {"id": 123, "name": "Player1", "power": 50000000, "kills": 10000}
  ]
}
```
 Fácil de parsear e replicar

### Cenário 2: Protobuf
```
message: {1: 123, 2: "Player1", 3: 50000000}
```
 Ainda possível, precisa de engenharia reversa do schema

### Cenário 3: Dados Encriptados
```
Binário que não faz decode
```
 Provavelmente encriptação extra, muito mais difícil

---

## Próximos Passos (se dados forem acessíveis)

1. **Documentar endpoints descobertos**
2. **Criar cliente Python para API**
3. **Testar autenticação/sessões**
4. **Integrar com sistema existente**

---

## Notas de Segurança

 **IMPORTANTE:**
- Esta análise é para **fins educacionais/pesquisa**
- Viola os ToS do jogo
- Usar em conta secundária/teste
- Não distribuir ferramentas que automatizem exploits
- Considerar implicações legais na tua jurisdição
