# RoK Stats Project - Research Status

**Data:** 5 Fevereiro 2026  
**Pergunta:** porque é que o projecto ainda não faz localização instantânea ou
lookup directo por Player ID da mesma forma que alguns serviços comerciais?

## Resposta curta

Porque o caminho aberto e estável do projecto assenta em **ADB + OCR + API**,
enquanto essas funcionalidades exigem normalmente uma de duas coisas:

1. leitura directa de memória em runtime
2. intercepção ou descodificação consistente do protocolo de jogo

No Windows, o cliente do jogo tornou esses dois caminhos muito mais frágeis do
que o scanner OCR.

## O que já funciona bem

| Funcionalidade | Estado | Método atual |
|----------------|--------|--------------|
| Scan de stats | Funciona | OCR via Tesseract |
| Fila e bot de títulos | Funciona | Backend + runtime dedicado |
| Base de dados de governors | Funciona | API + base de dados |
| Registo de coordenadas conhecidas | Funciona | Dados recolhidos no workflow normal |

## O que travou a pesquisa no Windows

### 1. Hooks de memória com Frida

O bloqueio mais repetido foi:

```text
VirtualAllocEx returned 0x00000005 (ACCESS_DENIED)
```

Na prática, isso significou:

- attach frio instável ao processo Windows
- falhas frequentes ao tentar instalar hooks persistentes
- leituras pontuais ainda possíveis em alguns cenários, mas não uma base sólida
	para captura contínua

### 2. Captura de protocolo

As observações relevantes foram estas:

- o canal principal de jogo apareceu como tráfego binário customizado
- parte do tráfego HTTP visto em portas secundárias não era suficiente para o
	tipo de dados pretendido
- pinning, serialização interna e lógica do cliente dificultaram a extracção de
	um fluxo simples e reutilizável

### 3. Dump estático não chega

O dump IL2CPP ajudou a localizar classes, RVAs e bibliotecas relevantes, mas
isso por si só não resolveu o problema. Sem um attach estável ou um decoder de
protocolo maduro, o dump estático não entrega localizações instantâneas.

## O que provavelmente fazem ferramentas comerciais

Esta parte é inferência, não confirmação documental. Os caminhos mais prováveis
parecem ser:

### Caminho A: Android rooted

- emulador ou device rooted
- Frida e memory reading com menos fricção do que no cliente Windows
- hooks no `libil2cpp.so` ou noutras libs em runtime

### Caminho B: protocolo mais bem conhecido

- captures suficientes para descodificar mensagens úteis do jogo
- algum tipo de cliente ou parser interno especializado
- correlação entre identidade, posição e eventos de mapa

### Caminho C: aproveitar superfícies administrativas do próprio jogo

Em alguns testes e relatos externos, atribuir ou consultar certos estados no
jogo parece expor informação que não está disponível no fluxo OCR normal. Isso
é útil para pesquisa, mas não substitui um pipeline estável por si só.

## Leitura prática desta análise

Se o objectivo é manter o projecto utilizável, o caminho mais sensato continua
a ser:

1. usar o stack actual para produção
2. concentrar a pesquisa avançada num ambiente Android controlado
3. tratar o Windows como ambiente hostil para attach persistente

## Recomendação

### Para produção

Continuar com o workflow actual de backend, queue, scanner e runtime dedicado.
É menos glamoroso do que leitura directa de memória, mas é o que se mantém de
pé com menos regressões.

### Para pesquisa futura

Investigar primeiro no Android:

- `android_position_hook.js`
- `android_discovery.js`
- `rok_il2cpp_bridge.js`

Se houver próximo salto real neste projecto, é mais provável vir daí do que de
mais uma tentativa de cold attach no cliente Windows.

## Nota final

Leitura de memória, intercepção de tráfego e bypass de protecções podem violar
os ToS do jogo e trazer risco de ban. O caminho actual do projecto não elimina
esse risco, mas evita depender das técnicas mais frágeis do stack de pesquisa.
