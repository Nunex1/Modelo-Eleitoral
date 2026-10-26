# Redesign do Lampiadim — 26/10/2026

## Interface implementada

A aplicação abre em **Pergunte ao Lampiadim**. O compositor fica fixado na base
da área principal. A barra lateral nativa do Streamlit reúne primeiro turno
disponível, segundo turno pendente, nova conversa, histórico, dashboard,
privacidade e informações. Em telas pequenas ela pode ser recolhida.

Selecionar o segundo turno exibe a mensagem solicitada e suspende consultas
naquela tela. Voltar ao primeiro turno recupera o funcionamento. Não foi criada
uma base fictícia de segundo turno. A disponibilidade do primeiro turno exige
que os arquivos sejam carregados, validados e retornem votos.

O dashboard usa o mesmo mecanismo estatístico. Seus filtros ficam preservados
ao abrir chat, informações, privacidade ou o aviso do segundo turno. A navegação
usa rotas explícitas por parâmetro `pagina`: `conversa`, `dashboard`,
`privacidade` e `sobre`.

## Identidade oficial

A origem é o arquivo **image.png fornecido pelo usuário**, preservado na raiz.
Apesar da extensão, o conteúdo é JPEG RGB, 1122 × 1402, com fundo preto opaco.
O SHA-256 original está registrado em `Lampiadim_MVP/assets/identidade.json`.

Foi usada a ferramenta integrada **image_gen**, modo de edição
`background-extraction`, para remover o fundo. O resultado tem alpha real,
preserva a pose e a identidade do personagem e foi inspecionado sobre o fundo
creme da aplicação. Nenhum filtro CSS modifica as cores da ilustração.

Prompt usado:

> Use case: background-extraction. Edit target: the supplied official Lampiadim
> image, a blue Brazilian genie with leather cangaco hat, round gold glasses and
> traditional clothing.
> Remove ONLY the flat black background, producing true RGBA transparency.
> Preserve the exact original character identity, facial expression, pose,
> anatomy, hat, glasses, hands, leather details, gold objects, smoke-shaped blue
> tail, shadows and original colors. Do not redraw, reinterpret, redesign or
> replace the character. Do not add text, objects, backdrop, glow or a new
> shadow. Keep the entire character and all tail curls within the frame with
> minimal transparent padding. Clean antialiased edges, no black matte or halo.
> This is a faithful background cutout of the supplied image, not a new
> illustration. Output a single high-quality transparent PNG for a light cream
> website.

Arquivos locais:

| Arquivo em `Lampiadim_MVP/assets/` | Uso |
| --- | --- |
| `lampiadim_mascote.png` | Mestre transparente, 1122 × 1402 |
| `lampiadim_mascote.webp` | Ilustração completa otimizada, 480 × 600, 242.520 bytes |
| `lampiadim_avatar.svg` | Janela circular sobre o rosto da mesma imagem; cabeçalho, barra lateral, respostas e processamento |
| `lampiadim_favicon.svg` | Janela sobre o mesmo rosto, com imagem incorporada menor |
| `identidade.json` | Origem, hashes, dimensões e método |

Os SVGs não redesenham o personagem: incorporam uma versão da ilustração e
enquadram o rosto por `viewBox`. O cabeçalho pequeno exibe apenas o rosto; a
tela inicial conserva o personagem inteiro. Os caminhos são resolvidos a partir
do arquivo do módulo e não do diretório de execução. Todas as imagens estão no
projeto e no pacote portátil; não dependem de serviço externo na navegação.

`scripts/preparar_identidade.py` reproduz apenas a otimização e os enquadramentos
a partir do mestre aprovado. Ele não invoca IA nem altera o original.

## Privacidade

Página própria em `?pagina=privacidade`, acessível pela barra lateral e pelo
rodapé. Conteúdo em `Lampiadim_MVP/assets/politica_privacidade.md`.

O texto descreve o estado da sessão, filtros, modo local e integração opcional
com OpenAI, downloads, retenção, cookies técnicos e medidas existentes. Inclui
links para a LGPD e as orientações da ANPD consultadas em 26/10/2026. O controle
de exclusão remove as conversas da sessão atual; não promete apagar logs ou
arquivos baixados.

Permanecem explicitamente pendentes da identificação do responsável: controlador,
contato, bases legais documentadas, retenção de logs/backups, fornecedores e
condições de eventual transferência internacional. Não há declaração de
conformidade jurídica integral ou identidade fictícia de controlador.

## Arquivos alterados nesta revisão

- `Lampiadim_MVP/app.py`: navegação, barra lateral, início no chat, estados de
  turno, privacidade, informações, histórico e preservação de filtros.
- `Lampiadim_MVP/assets/styles.css`: estilos centralizados e responsivos.
- `Lampiadim_MVP/lampiadim/branding.py`: carregamento da identidade local.
- Arquivos de identidade e política listados acima.
- `scripts/preparar_identidade.py`: derivados reprodutíveis do mestre.
- `scripts/empacotar.py`: inclui e verifica imagens e política no ZIP.
- `tests/test_app.py`: regressão de navegação, contexto, histórico, filtros,
  turnos e privacidade.
- `README.md`, `docs/EXECUCAO.md`, este documento e evidências em `resultados/`.

`data.py`, `assistant.py`, `charts.py`, o notebook e os insumos eleitorais não
foram alterados pelo redesign. A reconciliação dos dados e os testes analíticos
foram executados novamente. Resultados e limites em
`resultados/VALIDACAO-REDESIGN.md`.
