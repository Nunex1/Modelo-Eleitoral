# Segundo turno, horários das urnas e simulação demográfica

Expansão do Lampiadim em três frentes:

1. o 2º turno de 2026 com as mesmas capacidades do 1º;
2. a análise temporal das urnas a partir dos logs oficiais;
3. um simulador hipotético de distribuição de votos.

Toda informação exibida tem uma natureza declarada:

- **DADO OFICIAL:** valor identificado diretamente nos registros eleitorais (votos, eleitores, contagens de log).
- **CÁLCULO ESTATÍSTICO:** operação determinística sobre dados oficiais (percentuais, diferenças, rankings, classificação de urna estendida).
- **SIMULAÇÃO HIPOTÉTICA:** cenário matemático sobre premissas, nunca verificável como comportamento individual.

A natureza aparece em cada resposta do chat (legenda e "Consultar fontes"), em cada `trace` de consulta e nas tabelas exportadas da simulação.

## 1. Segundo turno

**Fonte.** Em 26/10/2026 o arquivo consolidado `votacao_candidato_munzona_2026.zip` do TSE ainda continha apenas o 1º turno (modificado em 25/10, 13h16 de Brasília, antes do encerramento da votação). Os resultados oficiais do 2º turno vêm, por isso, do portal oficial de divulgação, `https://resultados.tse.jus.br/oficial/ele2026/6258/dados/<uf>/<uf><município>-c0001-e006258-u.json`: um arquivo por município, mais um por UF e um do Brasil.

- **Coleta:** `scripts/baixar_divulgacao.py 6258 6257`, com retomada e limite de requisições. Os arquivos brutos ficam em `dados/brutos/divulgacao_2026/` e o resumo da coleta (arquivos, falhas, SHA-256 do conjunto) em `_coleta.json`.
- **Preparação:** `scripts/preparar_dados.py --divulgacao` gera três arquivos:
  - `votos_divulgacao.parquet`, com os votos por município e candidatura, sem exterior;
  - `totalizacao.parquet`, com seções totalizadas, eleitorado apto, comparecimento, abstenção, válidos, brancos e nulos, nos dois turnos;
  - `candidatos.parquet`, acrescido das linhas do 2º turno: situação "ELEITO"/"NÃO ELEITO" e votos no exterior.
- **Validação na preparação:** a preparação aborta se qualquer conferência falhar.
  - A soma dos municípios deve ser igual ao total de cada UF, candidatura a candidatura.
  - A soma das UFs e do exterior deve ser igual ao total do Brasil.
  - Cada arquivo precisa declarar eleição, turno e município corretos.
  - **Equivalência das fontes:** o 1º turno da divulgação (eleição 6257) precisa coincidir linha a linha com o arquivo consolidado já usado (`votos.parquet`). Isso mostra que os números do 2º turno seguem a mesma definição dos do 1º.
- **Carregamento:** `ElectoralData` concatena os votos da divulgação apenas para turnos ausentes do arquivo consolidado. Quando o TSE publicar o consolidado com o 2º turno, ele prevalece automaticamente.

**Interface.** O botão "2º turno · Disponível" e o filtro "Turno" passam a valer ao mesmo tempo para:

- o dashboard;
- os indicadores e os mapas;
- a lista de candidaturas;
- o contexto da conversa ativa.

A aba "Resultados eleitorais" ganhou duas seções:

- **"Comparação entre turnos":** votos e percentual dos válidos de cada finalista nos dois turnos, cada turno com o próprio denominador, e uma tabela município a município exportável.
- **"Comparecimento oficial":** eleitorado apto, comparecimento, abstenção, brancos e nulos da totalização do turno selecionado. Os filtros de perfil não se aplicam, porque a totalização não tem recorte demográfico.

**Chat.** O turno selecionado na interface é contexto explícito. Sem esse contexto (uso programático), o assistente pergunta "1º ou 2º turno?". "Compare os dois turnos em Campinas" usa a ferramenta `comparar_turnos`.

## 2. Horários das urnas

**Fontes.**

- **2º turno, todo o Brasil:** `secoes.csv` do repositório [apolinario/urnas-tardias](https://github.com/apolinario/urnas-tardias), fixado por commit em `dados/brutos/urnas_tardias/<commit>/`, com SHA-256 no manifesto. O repositório não declara licença. Usamos apenas o dado derivado dos logs públicos do TSE, com atribuição; nenhum código dele foi copiado.
- **Coleta própria:** `scripts/coletar_logs_urna.py`, uma reimplementação da mesma metodologia a partir de `https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/<pleito>/`, pleito 3220 para o 1º turno e 3221 para o 2º. Ela guarda a contagem de votos computados por minuto de cada seção, o que permite a distribuição por faixa horária. Foi executada para Americana/SP e Campinas/SP nos dois turnos e para uma amostra sorteada de seções do 2º turno.

**Metodologia** (`scripts/preparar_dados.py --horarios`):

- **Eventos lidos no log:** "Urna pronta para receber votos" (abertura), "Procedimento de encerramento confirmado" (encerramento) e "O voto do eleitor foi computado" (um voto computado, sem candidatura).
- **Horário de Brasília:** os logs estão em horário local. O fuso de cada município é a moda de (abertura − 8h), porque a votação começou às 8h de Brasília em todo o país.
- **Urna estendida:** encerramento a partir de 17h45 de Brasília, mesmo critério do urnas-tardias.
- **Exterior:** fica fora, porque vota no horário local de cada país.
- **Horário do voto × encerramento da urna:** são grandezas distintas e aparecem separadas em todas as telas.
- **Validação cruzada:** as seções coletadas por nós no 2º turno são recalculadas e comparadas com o `secoes.csv` (abertura, encerramento, último voto, votos após 17h e 17h20, total). As divergências ficam no manifesto (`sources.timing.validacao_cruzada`). Uma verificação em tempo de consulta também confere que as faixas horárias somam os votos computados de cada seção.

**O que não é feito.**

- Nenhuma tabela temporal tem coluna de candidatura, e um teste garante isso. Perguntas como "Quantos votos Lula recebeu depois das 17h?" recebem: "Não é possível saber. Os registros das urnas marcam o horário em que cada voto foi computado, mas não a candidatura escolhida."
- Nenhum total é mostrado para um recorte em que algum município com seções totalizadas não tem registro de horário. No 1º turno, só Americana e Campinas foram coletados: uma pergunta sobre o Brasil ou São Paulo recebe a lista dos municípios cobertos, em vez de um total parcial que pareceria nacional.

**Interface.** A aba "Análise temporal" mostra:

- urnas com registro (com a cobertura sobre as seções totalizadas), urnas estendidas, votos após 17h e último voto;
- a distribuição por faixa horária, só onde a linha do tempo completa foi coletada;
- o encerramento em blocos de 15 minutos;
- o ranking por UF ou município;
- a tabela por zona e seção, exportável;
- o método.

## 3. Simulador estatístico de distribuição hipotética dos votos

**Fórmula (cenário proporcional, padrão).** Para cada grupo do recorte:

    participação do grupo = eleitores cadastrados no grupo ÷ eleitores cadastrados no território
    votos simulados do grupo = votos oficiais da candidatura × participação do grupo

**Cenário ponderado (exploratório).** O usuário escolhe um fator hipotético por categoria:

    peso ajustado = participação × fator
    votos simulados = votos oficiais × peso ajustado ÷ soma dos pesos ajustados

**Inteiros:** usa o método dos maiores restos. A soma é sempre igual ao total oficial e nenhum grupo se afasta mais de um voto do valor exato. **Dois recortes** usam a tabela conjunta oficial do cadastro (o perfil do TSE já é cruzado). Não há multiplicação de marginais nem suposição de independência.

**Composição.** É sempre a do território selecionado: município, UF, região, DDD ou Brasil. Os filtros de perfil do dashboard não se aplicam, porque a simulação precisa da composição completa para fechar o total.

**Transparência obrigatória:**

- **Faixa fixa:** em tom de alerta, com hachura, no topo da aba e de cada resposta do chat: "SIMULAÇÃO HIPOTÉTICA. NÃO REPRESENTA VOTOS REAIS POR PERFIL DEMOGRÁFICO."
- **Gráfico:** traz o mesmo aviso como anotação, a marca d'água "HIPOTÉTICO", barras hachuradas em âmbar (nunca a cor dos dados oficiais) e séries chamadas "votos simulados". A exportação de imagem preserva tudo, porque faz parte da figura.
- **Tabelas e CSV:** cada linha traz `Natureza = SIMULAÇÃO HIPOTÉTICA` e a coluna `Aviso`.
- **Detalhes:** fonte dos votos oficiais, fonte da composição, fórmula, hipótese estatística, limitações, cenário, fatores, data e versão das bases.

**Chat.**

- **Pedido explícito:** a simulação exige uma palavra de pedido ("simule", "simulação", "cenário hipotético"). "Agora faça a mesma simulação para Flávio Bolsonaro" mantém município, turno, recorte e fatores, trocando só a candidatura.
- **Voto real:** "Quantas mulheres realmente votaram em Lula em Campinas?" continua recebendo "Não é possível determinar…", nunca o resultado do simulador.
- **Com a IA externa:** uma simulação proposta pelo modelo sem pedido explícito do usuário é descartada.
- **Fatores pelo chat:** podem ser ditos ("peso 1,2 para mulheres"). No dashboard, há controles para qualquer categoria.

## Testes

`tests/test_expansao.py` cobre:

- a reconciliação dos totais do 2º turno com os arquivos oficiais lidos diretamente;
- o isolamento entre turnos;
- o exemplo obrigatório (100 votos, eleitorado 60/30/10 → 60/30/10) e o cenário ponderado;
- os maiores restos, grupos ausentes e a distribuição conjunta;
- os avisos em gráficos, tabelas e CSV;
- a separação entre pedido de simulação e pergunta sobre voto real;
- os horários vindos dos logs e nunca atribuídos a candidaturas;
- a natureza declarada em cada resposta.

Veja `resultados/VALIDACAO-EXPANSAO.md` para o que foi executado.
