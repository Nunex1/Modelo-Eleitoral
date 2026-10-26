# Validação da expansão: 2º turno, horários e simulação — 26/10/2026

Metodologia em [docs/SEGUNDO_TURNO_HORARIOS_SIMULACAO.md](../docs/SEGUNDO_TURNO_HORARIOS_SIMULACAO.md).

## Executado

### Testes

- **Suíte completa:** 159 testes aprovados, nenhum pulado (`resultados/testes-expansao.xml`).
  `tests/test_expansao.py` traz os testes 1–10 da especificação, os casos de
  borda (grupo ausente, zero votos, dimensão inexistente, fator fora do limite,
  distribuição conjunta) e as conferências com os arquivos oficiais lidos sem o
  pipeline.
- **Conjunto de referência:** 36 casos em `tests/avaliacao/referencias.json`,
  100% em todas as dimensões. Seis casos novos usam números reais conferidos de
  forma independente por `tests/referencia.py`:
  - votos do 2º turno, lidos direto do JSON oficial;
  - comparação entre turnos;
  - simulação por sexo e "a mesma simulação para Flávio Bolsonaro", com os
    maiores restos recalculados do CSV do notebook;
  - votos após 17h e urnas estendidas, lidos direto do `secoes.csv`.
  - Mediana de 16,9 ms por pergunta, p95 de 134 ms e máximo de 932 ms.

### 2º turno (eleição 6258)

- **Coleta:** 5.787 de 5.787 arquivos, 0 falhas. SHA-256 do conjunto
  `3e83dedabf85…`, geração na origem em 25/10/2026, 23h27.
- **Reconciliação:** municípios × UF × Brasil, candidatura a candidatura.
  - Lula: 64.256.232 votos (64.056.078 no Brasil e 200.154 no exterior).
  - Flávio Bolsonaro: 59.826.041 votos (59.654.544 no Brasil e 171.497 no exterior).
  - Válidos no Brasil, sem exterior: 123.710.622.
- **Americana/SP:**
  - 141.573 válidos: Lula 48.130, Flávio Bolsonaro 93.443.
  - Comparecimento de 147.134 sobre 181.214 aptos; 5.561 brancos e nulos.
  - Válidos + brancos + nulos = comparecimento.

### 1º turno pela divulgação (eleição 6257)

- **Coleta:** 5.787 de 5.787 arquivos, 0 falhas. SHA-256 `85dc4aa00713…`,
  geração na origem em 24/10/2026, 20h13.
- **Equivalência das fontes:** 66.852 linhas (município × candidatura) comparadas
  com `votos.parquet`, 0 divergências. Os votos do 2º turno seguem, portanto, a
  mesma definição dos do 1º.

### Totalização oficial (Brasil, sem exterior)

| | 1º turno | 2º turno |
|---|---:|---:|
| Seções totalizadas | 497.897 | 497.897 |
| Eleitorado apto | 157.828.968 | 157.828.819 |
| Comparecimento | 124.934.069 | 127.854.631 |
| Abstenção | 32.894.899 | 29.974.188 |
| Válidos | 118.969.906 | 123.710.622 |
| Brancos | 2.294.982 | 1.425.821 |
| Nulos | 3.669.181 | 2.718.188 |

- **Identidades:** aptos = comparecimento + abstenção e comparecimento =
  válidos + brancos + nulos, nos dois turnos.
- **Exterior:** 40 localidades têm seções totalizadas com comparecimento e
  abstenção zerados, e por isso aptos − comparecimento − abstenção dá 423. O
  painel e o chat usam apenas o Brasil.

### Horários das urnas

- **urnas-tardias:** `secoes.csv`, commit `5a41bc1d`, SHA-256 `2c9cbebf…`.
  - 497.882 urnas no Brasil, 7.352 estendidas (encerramento a partir de 17h45 de Brasília).
  - Os totais por município conferem com o CSV lido diretamente.
- **Coleta própria (pleito 3221):** Americana e Campinas completas (3.052
  seções) mais uma amostra sorteada do Brasil.
  - Validação cruzada: 3.197 seções, 0 divergências em abertura, encerramento,
    último voto, votos após 17h e 17h20, e total.
- **Reconciliação com o comparecimento oficial (2º turno):**
  - 4.804 de 5.571 municípios idênticos, nenhum com mais votos no log que no
    comparecimento.
  - 127.696.482 votos nos logs contra 127.854.631 de comparecimento: diferença de
    158.149 (0,12%).
  - 15 seções sem log.
- **Americana, 2º turno:** 517 urnas, 0 estendidas, 16 votos após 17h, último
  voto às 17h03min21s. As faixas horárias somam os votos computados.
- **Campinas, 2º turno:** 2.531 urnas, 12 estendidas (0,5%), 167 votos computados
  após 17h.

- **1º turno (pleito 3220):** Americana e Campinas completos.
  - 3.048 urnas com log, iguais às seções totalizadas. As 4 seções restantes da
    configuração não têm urna própria (aux.json 404 nos dois turnos).
  - 809.878 votos nos logs contra 810.838 de comparecimento: diferença de 960.
  - Americana: 517 urnas, 5 estendidas, 584 votos após 17h em 99 urnas, último
    voto às 18h17min04s. O teste confere a contagem de estendidas no JSONL bruto.
  - Campinas: 2.531 urnas, 10 estendidas, 2.511 votos após 17h.
- **Cobertura parcial recusada:** um recorte com municípios sem logs (Brasil ou
  SP no 1º turno) não recebe total. O chat e o painel listam os municípios
  cobertos.

### Simulação

- **Exemplo obrigatório:** 100 votos e eleitorado 60/30/10 resultam em 60/30/10.
- **Americana, 2º turno, por sexo:**
  - Lula: Feminino 25.522, Masculino 22.591, Não informado 17 (total 48.130).
  - Flávio Bolsonaro: 49.550, 43.861 e 32 (total 93.443).
- **Recusas mantidas:**
  - "Quantas mulheres realmente votaram em Lula em Campinas?" recebe "Não é
    possível determinar.", sem números.
  - "Quantos votos Lula recebeu depois das 17h?" recebe "Não é possível saber.",
    sem números.

### Navegador local (Streamlit, porta 8502)

- **2º turno, Americana:**
  - indicadores, mapa e lista de candidaturas mudaram com o botão "2º turno";
  - "Comparação entre turnos": gráfico, tabela e denominadores de cada turno;
  - "Comparecimento oficial": aptos, comparecimento, abstenção, brancos e nulos.
- **Análise temporal:** cartões, faixa horária, encerramento em blocos de 15
  minutos (escala log com rótulos inteiros), ranking, tabela por seção e método.
  - Conferida no 2º turno em Americana e no 1º turno em Americana.
  - No 1º turno com recorte Brasil, aparece a mensagem de cobertura parcial.
- **Simulações:** faixa de aviso, gráfico com aviso, marca d'água e hachura,
  tabela e CSV com `Natureza` e `Aviso`.
  - Em 375 px de largura, o aviso do gráfico estava cortado. Ele foi quebrado em
    três linhas e conferido de novo.
- **Chat:** simulação, "a mesma simulação para Flávio Bolsonaro" e as duas recusas.

### Correções feitas durante a validação

- **"Compare os dois turnos em Campinas":** sem contexto, a pergunta pedia "Quais
  candidaturas você quer comparar?", porque "os dois" era lido como referência a
  duas candidaturas. As expressões de turno agora são removidas antes dessa
  leitura. Virou caso de referência.
- **Aviso desatualizado:** o painel dizia que comparecimento e abstenção estavam
  indisponíveis. Agora mostra a totalização oficial quando ela existe.
- **Total parcial com cara de nacional:** depois da integração dos logs do 1º
  turno, a aba temporal no Brasil mostrava "3.048 urnas" e uma "diferença de
  124 milhões" em relação ao comparecimento. Esses números somavam só Americana e
  Campinas. Agora a consulta é recusada quando falta algum município do recorte.
  Há teste no chat e no app.

## Não verificado e limites

- **Chamada real ao provedor de LLM:** não há credencial no ambiente. As novas
  ferramentas (`simular_distribuicao_demografica`, `consultar_horarios`,
  `comparar_turnos`) foram testadas com respostas simuladas do provedor.
- **Faixa horária:** existe só onde coletamos a linha do tempo completa
  (Americana e Campinas). No resto do Brasil há encerramento, último voto e votos
  após 17h e 17h20, que vêm do urnas-tardias.
- **Horários do 1º turno:** só Americana e Campinas.
  O `secoes.csv` fixado do urnas-tardias cobre só o 2º turno, e a coleta nacional
  do 1º (cerca de 500 mil logs) não foi feita.
- **Logs × comparecimento:** os logs contam 158.149 votos a menos que o
  comparecimento oficial do 2º turno. A diferença é informada na interface e no
  manifesto, e não é corrigida.
- **Fonte do 2º turno:** é o portal de divulgação até o TSE publicar o arquivo
  consolidado, que passará a prevalecer automaticamente.
- **Licença do urnas-tardias:** o repositório não declara licença. Usamos só o
  dado derivado de logs públicos do TSE, com atribuição; nenhum código foi copiado.
- **Ferramentas não executadas:** `pyflakes` não está instalado neste ambiente;
  `compileall` e `git diff --check` foram executados. Build Docker e
  `resultados/Lampiadim-local.zip` não foram regerados.
