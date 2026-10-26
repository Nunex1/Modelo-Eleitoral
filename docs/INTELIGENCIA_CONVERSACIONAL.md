# Inteligência conversacional do Lampiadim

O Lampiadim é uma interface de linguagem natural para a base eleitoral local.
A interpretação entende a pergunta, o banco fornece os fatos, o motor estatístico
calcula, o verificador confere e o gerador comunica somente o que foi pedido.

## Diagnóstico da arquitetura encontrada

- Python 3.13, Pandas 3 e Streamlit 1.66 (`Lampiadim_MVP/app.py`). Não há API
  HTTP própria nem banco SQL: os dados são Parquets locais carregados em memória
  (`ElectoralData`, com conferência de SHA-256), e não há DuckDB instalado.
- O chat (`chat()` em `app.py`) guardava mensagens e um `Filters` por conversa
  em `st.session_state`, sem persistência. Esse modelo de privacidade foi mantido.
- O assistente anterior combinava palavras-chave a uma chamada opcional à OpenAI
  (`OPENAI_API_KEY` e `OPENAI_MODEL`), com saída estruturada para uma intenção
  simples. A integração foi preservada e ampliada.
- Bases: votação presidencial de 2026, 1º turno, por município e candidatura
  (sem exterior), perfil do eleitorado de 2026 (sexo, identidade de gênero, faixa
  etária, escolaridade), municípios com DDD Anatel e, agora, metadados oficiais
  das candidaturas (`candidatos.parquet`).
- Limites reais na época: não havia 2º turno, outros anos, comparecimento,
  abstenção, brancos/nulos, raça/cor, renda nem estado civil na base preparada.
  O 2º turno, a totalização e os horários das urnas foram integrados depois
  (veja [SEGUNDO_TURNO_HORARIOS_SIMULACAO.md](SEGUNDO_TURNO_HORARIOS_SIMULACAO.md)).

## Camadas implementadas

| Camada | Módulo | Responsabilidade |
|---|---|---|
| 1. Interpretação semântica | `interpreter.py` (local) e `llm.py` (OpenAI) | Intenção, entidades, filtros, métrica, referências ao contexto e ambiguidades |
| 2. Estruturação | `context.py` (`Frame`, `ConversationState`) e `planner.py` | Combina a pergunta com o contexto e produz um `Plan` tipado |
| 3. Validação | `tools.validate` e `planner.py` | Entidade existe, candidatura participou do pleito, período e métrica disponíveis, limites |
| 4. Motor estatístico | `engine.py` | Consultas somente leitura em Pandas sobre os Parquets, com agregações pré-calculadas |
| 5. Verificação | `verification.py` | Somas, denominadores, duplicidades, faixas válidas e recálculo pelo caminho do dashboard |
| 6. Resposta | `responses.py` | Modelos determinísticos, formatação pt-BR e conferência da origem de cada número |

`assistant.answer_question` orquestra o fluxo. Perguntas compostas são divididas
em orações e respondidas em sequência, e o contexto passa de uma oração para a seguinte.

### Interpretação local

Funciona sem credenciais e em todos os testes. Ela não depende de frases fixas:

- normaliza acentos, caixa, pontuação, abreviações informais (`qts`, `pra`, `vc`),
  vícios de linguagem (`mano`, `tipo`) e erros de digitação do vocabulário de domínio;
- reconhece entidades pelo maior trecho válido: nomes de urna, nomes completos e
  subnomes distintivos das candidaturas, municípios, UFs, siglas, gentílicos
  ("paulistas"), apelidos verificados (Sampa, BH, capital paulista), regiões do
  IBGE, DDD, partidos e categorias oficiais do cadastro;
- usa pistas sintáticas do português ("estado de", "cidade de", artigo em "no
  Paraná", "/SP" depois do município, ordinais, pronomes como "ele", "os dois" e "lá");
- aplica correspondência aproximada apenas quando ela é única ("Bolsonaru", "Campnas");
- nomes de município que também são palavras comuns (Vitória, União, Contagem)
  exigem pista de lugar.

### Interpretação por modelo de linguagem (opcional)

Com `OPENAI_API_KEY` e `OPENAI_MODEL` no ambiente do servidor, a pergunta é
enviada à Responses API com 17 ferramentas em *function calling* estrito
(`tool_choice: "required"`, `store: false`, timeout de 20 s). O modelo recebe a
pergunta, o contexto estruturado (entidades em foco, sem texto de mensagens
anteriores), a lista pública de candidaturas e os períodos disponíveis. Ele
**apenas escolhe ferramentas e argumentos**: cada nome é revalidado na base, a
execução é local e o texto é gerado por modelos determinísticos. Antes da chamada,
as travas locais (inferência demográfica, métricas indisponíveis, opinião,
previsão) respondem sem consultar o provedor, e uma ambiguidade geográfica
detectada localmente prevalece sobre a escolha do modelo. Se a chamada falhar ou
violar o contrato, a interpretação local assume e a resposta indica
"IA indisponível nesta resposta". As instruções permanentes estão em
`llm.INSTRUCTIONS` e reproduzem a seção 18 da especificação.

**Não houve chamada real ao provedor**: o ambiente não tem credencial nem modelo
configurados. O contrato (formato das ferramentas, validação, fallback e travas)
é testado com respostas simuladas do provedor.

## Ferramentas

Definidas em `tools.TOOLS`, cada uma declara parâmetros, tipos, obrigatoriedade,
regra de validação, retorno, fonte e limites. Todas são somente leitura.

| Ferramenta | Uso |
|---|---|
| `consultar_votos` | votos, percentual dos válidos e colocação de candidaturas num território |
| `consultar_resultado_territorial` | vencedor, colocação, resultado completo, total de válidos |
| `comparar_candidatos` | quem teve mais, diferença em votos, em pontos percentuais e variação relativa |
| `comparar_territorios` | mesma métrica em 2 a 6 territórios, com denominadores próprios |
| `gerar_ranking_municipal` | ranking de municípios ou UFs por votos, percentual, válidos ou eleitorado; empates no corte incluídos |
| `contar_vitorias` | municípios/UFs em que a candidatura foi a mais votada; empates no topo à parte |
| `consultar_eleitorado` | eleitores cadastrados, opcionalmente numa interseção de categorias |
| `consultar_distribuicao_demografica` | distribuição do cadastro por dimensão |
| `consultar_candidaturas` | lista, número, partido, nome completo, classificados para o 2º turno |
| `contar_municipios` | municípios de um território (e lacunas de DDD) |
| `comparar_turnos` | votos e % dos válidos de cada candidatura nos dois turnos, cada turno com o próprio denominador |
| `consultar_horarios` | urnas com registro, urnas estendidas, votos computados após um horário, último voto, faixas horárias e ranking; nunca por candidatura |
| `simular_distribuicao_demografica` | cenário hipotético proporcional ou ponderado; só com pedido explícito de simulação |

O contrato com o modelo de linguagem acrescenta quatro ferramentas de controle:
`continuar_consulta_anterior`, `informar_limitacao`, `pedir_esclarecimento` e
`conversa`.

Cada resultado declara sua natureza em `trace["natureza"]`, na legenda e em
"Consultar fontes": **DADO OFICIAL** (votos, eleitores, contagens de log),
**CÁLCULO ESTATÍSTICO** (percentuais, diferenças, rankings, comparações) ou
**SIMULAÇÃO HIPOTÉTICA** (somente `simular_distribuicao_demografica`, sempre com
o aviso "SIMULAÇÃO HIPOTÉTICA. NÃO REPRESENTA VOTOS REAIS POR PERFIL
DEMOGRÁFICO.", fórmula, hipótese e fontes).

A resolução de entidades (`entities.KnowledgeBase`) e a checagem de
disponibilidade (`tools.validate` e `planner`) são as ferramentas conceituais
`resolver_entidade_eleitoral` e `validar_disponibilidade_de_dados`.

## Contexto e ambiguidade

`ConversationState` guarda candidaturas e territórios em foco, mencionados
recentemente, período, intenção, métrica, escopo do último ranking, os dois
primeiros do último resultado e um esclarecimento pendente. Uma pergunta que muda
só uma dimensão ("E Bolsonaro?", "E em Americana?", "E no segundo?", "Na
verdade, Campinas") preserva as demais. Uma pergunta nova com outras entidades
não herda filtros incompatíveis, e cada conversa nova começa vazia, com os
filtros do painel como ponto de partida.

- **A — clara:** executa.
- **B — recuperável:** completa pelo contexto ou pelos filtros do painel. Quando
  a base tem um único período, ele é usado e sempre citado na resposta.
- **C — ambiguidade material:** uma pergunta curta, como estado ou município,
  qual UF de um homônimo, ano ou turno, completo ou incompleto, votos ou
  percentual. A resposta seguinte ("a cidade", "PR", "2022", "sim") completa a
  consulta pendente.

## Regras estatísticas

- Percentual = votos da candidatura ÷ votos válidos de todas as candidaturas no
  mesmo território e turno × 100. O total "no Brasil" exclui o exterior, que pode
  ser consultado à parte ou somado ("incluindo o exterior").
- Diferença de percentuais é dada em **pontos percentuais**. "Quantos por cento a
  mais" é **variação relativa**.
- Rankings de "cidades que mais votaram" usam votos absolutos, salvo pedido de percentual.
- Votos e cadastro não se misturam. Perguntas que associam grupo demográfico a
  voto recebem "Não é possível determinar…". Uma razão entre votos e cadastro é
  recusada, e o assistente oferece o percentual sobre os válidos. A simulação
  demográfica só responde a um pedido explícito ("simule"), e frases como
  "realmente votaram" a desativam.
- Horários vêm dos logs das urnas, que não registram candidatura. "Quantos votos
  Lula recebeu depois das 17h?" é recusada com essa explicação.
- Com dois turnos na base, o turno selecionado na interface é contexto explícito.
  Sem ele, o assistente pergunta "1º ou 2º turno?".
- Faixas etárias só são somadas quando coincidem exatamente com as faixas
  oficiais; "jovens" e "idosos" exigem definição.
- DDD é área telefônica. A cobertura parcial de uma UF é informada.
- Formato brasileiro: `37.768`, `27,7%`, `35,9 pontos percentuais`. Os cálculos
  usam precisão total. A exibição usa uma casa e aumenta quando dois valores
  diferentes ficariam iguais ou quando um valor positivo pareceria zero.

## Controles contra alucinação e entradas maliciosas

- Nenhum número é escrito por modelo de linguagem. O `Writer` registra cada
  número formatado, e `verify_grounded_text` bloqueia a resposta se aparecer um
  número sem origem.
- Os resultados são conferidos por invariantes e pelo `ElectoralData.query` do
  dashboard. Se a verificação falha, a resposta diz que não foi possível validar.
- Falha de leitura → "Não consegui consultar a base…", sem números.
- SQL, HTML e scripts são recusados. Textos do usuário só voltam sanitizados.
  Números afirmados pelo usuário ("100 mil votos, né?") são confrontados com a
  base: "Sim.", "Não." ou "Aproximadamente.".
- Logs técnicos (`lampiadim.consultas`, `lampiadim.assistente`) registram
  ferramenta, status e duração, nunca o conteúdo das perguntas.

## Rastreabilidade

Cada consulta produz um `trace`: ferramenta, fonte, versão (data de geração e
SHA-256), ano, turno, filtros, métrica, denominador, registros processados,
resultado, status de validação e duração. A interface mostra esse resumo em
"Consultar fontes e denominadores".

## Dados adicionados

`scripts/preparar_dados.py --only-candidates` gera `candidatos.parquet` a partir
do arquivo BR do TSE já presente, com nome completo, partido, coligação, situação
na totalização e votos no exterior. O script reconcilia os votos sem exterior
com `votos.parquet` e registra hash e fonte no `manifest.json`. A preparação
completa também gera o arquivo. Sem ele, o assistente reconhece apenas os nomes de urna.

## Testes e avaliação

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe scripts\avaliar_lampiadim.py
```

- `tests/test_conversational.py`: os 25 cenários da especificação e as 15
  avaliações adicionais.
- `tests/test_assistant.py`: contrato com o provedor e regressões.
- `tests/test_avaliacao.py`: conjunto de referência.
- `tests/referencia.py`: consultas de referência independentes, calculadas dos
  CSVs originais do notebook.
- `conftest.synthetic`: base sintética com dois anos, dois turnos, empates e
  município sem votos, para cenários que a base real não contém.
- `scripts/avaliar_lampiadim.py` mede separadamente intenção, entidades,
  consulta, exatidão numérica, contexto, disciplina, alucinação, ambiguidade,
  resiliência e latência. Grava `resultados/avaliacao-lampiadim.{json,md}`.
  Toda falha nova deve virar um caso em `tests/avaliacao/referencias.json`.

## Limitações conhecidas

- O intérprete local é baseado em regras linguísticas e léxico de domínio, sem
  aprendizado estatístico. Formulações muito distantes dos padrões cobertos podem
  pedir esclarecimento em vez de responder. O modo com modelo de linguagem amplia
  essa cobertura, mas não foi homologado com um provedor real.
- A base contém 2026, 1º e 2º turnos presidenciais. A lógica de ano ambíguo foi
  validada com a base sintética.
- Desempenho medido localmente: mediana de ~10 ms por pergunta e p95 de ~120 ms.
  Consultas nacionais ao cadastro levam até ~0,7 s, por causa da verificação
  independente.
