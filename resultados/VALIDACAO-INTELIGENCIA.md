# Validação da inteligência conversacional — 26/10/2026

## Executado

- Suíte completa: **119 testes aprovados** (`resultados/testes-inteligencia.xml`).
  Inclui os 25 cenários da especificação, as 15 avaliações adicionais, o contrato
  com o provedor de LLM, as regressões do dashboard e a navegação Streamlit.
- Conjunto de referência (`tests/avaliacao/referencias.json`, 27 casos): 100% em
  intenção, entidades, consulta, exatidão numérica, contexto, disciplina,
  controle de alucinação, ambiguidade e resiliência. Mediana de 10 ms por
  pergunta, p95 de 122 ms, máximo de 221 ms. Detalhes em
  `resultados/avaliacao-lampiadim.md` e `.json`. As taxas valem para esse
  conjunto, não para qualquer pergunta possível.
- Valores esperados: consultas de referência independentes, calculadas dos CSVs
  originais do notebook (`tests/referencia.py`). Exemplos conferidos: Lula em
  Americana, 37.768 votos (27,7% dos válidos); Flavio Bolsonaro, 86.854; diferença
  de 49.086 votos (35,9 p.p.); Campinas, 870.672 eleitores; DDD 19, 4.310.963 eleitores.
- Preparação: `candidatos.parquet` gerado a partir do arquivo BR do TSE e
  reconciliado com `votos.parquet` (118.969.906 votos no Brasil, 330.882 no
  exterior). Hash registrado no manifesto e conferido no carregamento.
- Navegador local (Streamlit, porta 8502): conversa "Lula em Campinas → E
  Bolsonaro? → E em Americana? → Agora compara os dois → cinco cidades paulistas
  com mais votos para Lula" respondida com os valores de referência. O painel
  "Consultar fontes e denominadores" mostrou a rastreabilidade. O console não
  registrou erros.
- `pyflakes` sem avisos nos módulos novos, `compileall` e `git diff --check` executados.

## Não verificado

- **Chamada real ao provedor de LLM**: não há `OPENAI_API_KEY` nem `OPENAI_MODEL`
  no ambiente. O formato das ferramentas segue a documentação de *function
  calling* da Responses API e foi testado com respostas simuladas. Isso não
  equivale a homologação com o provedor.
- 2º turno, outros anos, comparecimento, brancos/nulos, raça, renda e estado
  civil: ausentes da base. O assistente informa a ausência e não estima.
  Ano e turno ambíguos foram validados com uma base sintética.
- Build Docker e deploy remoto não foram executados nesta etapa. Nenhuma
  dependência nova foi adicionada, e o Dockerfile já copia os módulos e os
  derivados (inclusive `candidatos.parquet`).
- `resultados/Lampiadim-local.zip` não foi regerado. Execute `scripts/empacotar.py`
  para incluir os novos módulos e dados.
