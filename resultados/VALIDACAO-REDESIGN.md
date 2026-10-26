# Validação do redesign — 26/10/2026

Implementação e verificações locais em Python 3.13.14, Streamlit 1.66.1 e
navegador Chromium integrado. Não houve publicação externa.

## Testes automatizados

Comando executado:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --junitxml=resultados/testes-redesign.xml
```

**38 testes passaram em 28,40 segundos.** Evidência: `testes-redesign.xml`.
Incluem reconciliação dos insumos reais, denominadores, recortes demográficos,
DDD, CSV reaberto, contexto do assistente, contrato do provedor, navegação e
seleção cartográfica via estado. Durante o desenvolvimento, uma regressão de
preservação dos filtros foi detectada e corrigida; a suíte final passou.

## Requisitos verificados

| Requisito | Evidência |
| --- | --- |
| Logo oficial no cabeçalho | Imagens carregadas no DOM e inspeção visual em desktop, tablet e tela estreita; em 390 px, apenas o rosto no cabeçalho |
| Avatar nas respostas | Consulta real sobre Americana/SP; rosto oficial à esquerda e pergunta à direita, em `redesign-chat.png` |
| Favicon | Ícone da página referencia o SVG incorporado local `lampiadim_favicon.svg`, com o mesmo enquadramento facial do avatar |
| Ilustração oficial no início | WebP 480 × 600 carregado, personagem completo, proporção preservada e fundo creme visível |
| Primeiro e segundo turnos na barra lateral | Botões disponíveis e operáveis em desktop e 390 px |
| Segundo turno pendente | Mensagem exata solicitada, sem input de consulta nem métricas de segundo turno; `redesign-segundo-turno.png` |
| Retorno ao primeiro turno | Botão de retorno reabilita chat; consulta Americana/SP retorna 136.589 votos nominais válidos |
| Dashboard | Navegação e filtros de SP/Americana; total preservado após ida e volta ao chat; clique em SP no mapa retornou 24.882.948 votos e limpar retornou ao Brasil; `redesign-dashboard.png` |
| Política de Privacidade | Rota própria, acesso pelo rodapé e barra lateral; pendências do controlador explícitas; `redesign-privacidade.png` |
| Responsividade | Viewports 1440 × 1000, 768 × 1024 e 390 × 844; sem rolagem horizontal da página; sugestões legíveis e compositor fixado |
| Histórico | Nova conversa cria uma sessão de conversa vazia; reabrir o item anterior recupera a resposta e o contexto de Americana/SP |
| Resultados preservados | 118.969.906 votos nacionais, 157.826.587 eleitores cadastrados e 136.589 votos em Americana/SP; reconciliação integral nos testes |

O botão de exclusão do histórico foi verificado pelo AppTest: remove as
conversas da sessão e cria uma conversa vazia. A política distingue esse efeito
da exclusão de arquivos baixados ou registros externos.

## Arquivos visuais e integridade

- Original `image.png`: JPEG RGB 1122 × 1402, SHA-256 preservado
  `18de69ce52383129f568eb4ab2619d191df8b4de8f931fde14efdb9626ff3061`.
- Mestre `lampiadim_mascote.png`: PNG RGBA 1122 × 1402, alpha de 0 a 255,
  53,88% dos pixels totalmente transparentes; fonte preservada na raiz.
- WebP sem perdas, avatar e favicon com enquadramentos da mesma imagem.
- Inspeção visual sobre a cor creme: personagem inteiro nas boas-vindas,
  chapéu/óculos/rosto reconhecíveis e ausência do retângulo preto original.
- `git diff --check` sem erros; notebook e CSVs originais sem diff.
- Compilação dos módulos Python sem erros; console do navegador sem erros
  capturados na verificação final.

## Limites da validação

São testes locais e em viewports simulados. Não equivalem a testes em aparelhos
físicos, Safari/Firefox, leitor de tela ou hospedagem pública. A integração com
IA externa continua desativada neste ambiente; seu contrato é testado com
respostas controladas, sem chamada real a um provedor.

Os dados do segundo turno continuam pendentes. A política é uma minuta fiel à
implementação: controlador, contato, bases legais, retenção de infraestrutura
e condições dos fornecedores ainda dependem de preenchimento pelo responsável
antes de publicação. Docker e publicação externa não foram executados.
