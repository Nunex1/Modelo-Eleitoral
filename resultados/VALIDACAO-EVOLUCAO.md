# Entrega e validação — evolução eleitoral do Lampiadim

Implementação e testes: 26/10/2026. Conferência final de disponibilidade:
27/10/2026. Implementação e validação **locais**, no repositório Modelo
Eleitoral. Aplicação disponível nesta sessão em http://127.0.0.1:8501/?pagina=dashboard.
Selecione **2º turno → Resultados eleitorais**. Não foi realizado deploy remoto.

## Resultado entregue

| Área | Comportamento implementado |
|---|---|
| Infográfico principal | Três etapas: primeiro turno, mudanças matemáticas e segundo turno; cartões, barras, cascata, síntese dinâmica e aviso de não identificação de fluxos |
| Estatística | Contagens, taxas com denominadores explícitos, diferenças absolutas, relativas e em pontos percentuais; decomposição simétrica com frações exatas |
| Comparecimento | Aptos, comparecimento e abstenção nos dois turnos, diferenças e barras comparativas |
| Brancos e nulos | Contagens e taxas separadas/conjuntas, composição do comparecimento e categorias técnicas sem dupla contagem |
| Composição integrada | Duas barras sobre aptos de cada turno, seletor de categoria com valores e variações e tabela alternativa |
| Territórios | Região, UF, DDD validado e município; mapas locais do IBGE; rankings por quantidade, taxa, variação absoluta, relativa e p.p.; mediana/P10/P90 identificados como não ponderados |
| Hipóteses | Transporte linear com margens oficiais, retenções e transferências ajustáveis, três objetivos, até nove combinações de sensibilidade, limites matemáticos e Sankey apenas quando viável |
| Assistente | Consultas locais aos mesmos indicadores validados; perguntas de crescimento, abstenção, brancos/nulos e rankings; troca de filtro sincroniza o contexto sem apagar mensagens |
| Proteções | Nenhuma inferência individual de migração ou atribuição de horário a candidatura; filtros demográficos não alteram totais eleitorais oficiais |
| Exportações | CSV com fontes, definições e versões; PNG consolidado; PDF consolidado com ranking selecionado; CSV/PDF separados para hipótese |
| Integração | Primeiro turno, navegação, logotipo, histórico temporário, privacidade, análise temporal e simulador demográfico existentes preservados |

Os campos de DDD e UF atuam em interseção também no chat e no motor. O teste do
DDD 61 com GO verifica que não são incluídos municípios do DF; uma pergunta
explícita por outro território pode substituir o recorte do painel.

## Evidências executadas

| Verificação | Resultado |
|---|---|
| Suíte anterior às alterações | 159 testes aprovados, 81,90 s |
| Suíte final completa | **198 aprovados, 0 falhas**, 133,64 s |
| Testes novos de estatística/conversa/exportação | 37 aprovados na execução isolada, 6,48 s; incluídos na suíte final |
| Streamlit AppTest | Dois fluxos novos incluídos na suíte final: filtros/chat/exportações/primeiro turno e laboratório com dados reais |
| Compilação Python | `compileall` sem erros |
| Consistência de alterações | `git diff --check` sem erros; apenas avisos informativos de convenção LF/CRLF |
| Auditoria de fontes | 11.514 linhas município/localidade × turno, reconciliadas com UFs e total nacional com exterior |
| Consultas remotas TSE | Seis JSONs: Brasil, Americana e Campinas, em ambos os turnos; contagens e votos iguais aos snapshots locais |
| Desktop | 1440 × 1000; largura do documento 1440 px |
| Tablet | 768 × 1024; largura do documento 768 px |
| Celular | 390 × 844; largura do documento 390 px; cascata e legendas legíveis |
| Navegador | Nenhum erro de console capturado na revisão das telas; tamanho de janela restaurado após os testes |
| Arquivos exportados | PNG aberto; PDF efetivamente renderizado por Poppler e inspecionado visualmente; CSV conserva dados e metadados |

Comando da suíte final:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q --junitxml=resultados/evolucao-testes.xml
```

O [JUnit XML](evolucao-testes.xml) registra os casos e tempos. Os testes cobrem
denominadores zero, frações exatas, taxas ponderadas pelas contagens, chaves
duplicadas, ausências, valores negativos/fracionários, esquema quebrado,
totalização parcial, cobertura desigual e divergência de votos nominais. Também
verificam conservação de margens, cenários inviáveis, proteção contra respostas
externas indevidas, continuidade de conversa e agregação nacional com cache.
Dados artificiais são restritos a testes matemáticos e de erro.

Na preparação do PR, foi conferido também o conteúdo efetivamente armazenado
no índice do Git: os dez arquivos do manifesto preservam seus SHA256. O JSON de
referências é gerado e versionado com LF explícito para evitar divergência após
clone no Windows. Após esse ajuste de serialização, os 37 testes de evolução
passaram novamente, em 11,33 s.

As seis verificações remotas ocorreram entre 19:29:34 e 19:29:38 UTC de
26/10/2026. URLs, hashes e horários individuais estão em
[referencias_totalizacao.json](../dados/tratados/lampiadim/referencias_totalizacao.json).
Isso comprova os snapshots daquela consulta; não é monitoramento contínuo.

## Conferências numéricas

Brasil **sem exterior**, recorte padrão explicitamente rotulado:

| Indicador | Primeiro turno | Segundo turno |
|---|---:|---:|
| Aptos publicados no recorte | 157.828.968 | 157.828.819 |
| Comparecimento | 124.934.069 | 127.854.631 |
| Abstenção | 32.894.899 | 29.974.188 |
| Válidos | 118.969.906 | 123.710.622 |
| Brancos | 2.294.982 | 1.425.821 |
| Nulos totais | 3.669.181 | 2.718.188 |
| Lula | 53.722.151 | 64.056.078 |
| Flávio Bolsonaro | 55.960.603 | 59.654.544 |

Crescimento líquido de Lula: **10.333.927 votos**, **19,24%** em relação à
quantidade inicial; participação de **45,16% para 51,78%** dos válidos. Efeitos
matemáticos exibidos: participação **8.036.219,34** e base válida **2.297.707,66**.
Internamente a soma é exata, antes do arredondamento de exibição.

Americana: Lula 37.768 → 48.130; abstenção 38.077 → 34.080. Campinas:
Lula 241.972 → 303.914. Os testes confrontam esses valores com os JSONs brutos,
além de testar a consulta conversacional.

## Limitações explícitas

- A [nota do TSE](https://dadosabertos.tse.jus.br/dataset/resultados-2026)
  documenta 39 duplicidades de transferência temporária: 158.745.502 registros
  publicados e 158.745.463 eleitores efetivos. O denominador nacional efetivo é
  aplicado uma única vez; nenhuma correção é distribuída arbitrariamente a UFs
  ou municípios.
- Os JSONs nacionais incluem 423 aptos em seções não instaladas no exterior.
  Por isso, comparecimento + abstenção não esgotam os aptos publicados. Essa
  diferença técnica é apresentada separadamente.
- A matriz fica bloqueada em Brasil sem exterior, Americana e Campinas porque
  os aptos diferem entre turnos. No total com exterior há ainda categorias
  técnicas não alocáveis. Isso cumpre a exigência de não fabricar fluxos para
  fechar margens incompatíveis.
- Em recortes cujas margens fecham, igualdade de totais não comprova que sejam
  as mesmas pessoas. O usuário precisa declarar essa hipótese; o resultado
  permanece uma massa hipotética, sem identificação individual.
- O mapa municipal é desenhado para recortes de até 800 localidades. Para
  recortes maiores, é solicitado filtro de UF; ranking e CSV completo continuam
  disponíveis. Associações DDD/IBGE ausentes seguem sinalizadas.
- O PDF é rasterizado. Para seleção de texto e leitura estruturada, há CSV e
  tabelas na interface. Não foi feita homologação manual com leitor de tela.
- Responsividade foi verificada no navegador incorporado em Windows. Não foi
  executada uma matriz de dispositivos físicos ou Safari/Firefox.
- A validação acima é local e não comprova deploy em produção. Atualizações
  posteriores de dados exigem coleta, preparação e nova auditoria.

## Arquivos criados e modificados

| Arquivos | Responsabilidade |
|---|---|
| `Lampiadim_MVP/lampiadim/evolution.py` (novo) | Serviço estatístico, validação, cache, decomposição e tabela de exportação |
| `Lampiadim_MVP/lampiadim/transfers.py` (novo) | Restrições, transporte linear, sensibilidade e limites |
| `Lampiadim_MVP/lampiadim/evolution_charts.py` (novo) | Cascata, barras, mapa e Sankey |
| `Lampiadim_MVP/lampiadim/evolution_ui.py` (novo) | Infográficos, laboratório, ranking, metodologia e downloads |
| `Lampiadim_MVP/lampiadim/evolution_exports.py` (novo) | Geração local de PNG/PDF e suplementos |
| `Lampiadim_MVP/app.py`, `assets/styles.css` | Integração, filtros, sincronização de conversa e responsividade |
| `lampiadim/data.py`, `engine.py`, `entities.py`, `verification.py` | Região e consistência da interseção UF/DDD |
| `lampiadim/assistant.py`, `interpreter.py`, `planner.py`, `responses.py`, `tools.py` | Intenções, contexto, consultas, respostas fundamentadas e proteções |
| `Lampiadim_MVP/requirements.txt` | Declaração de SciPy e Pillow, já presentes no ambiente científico |
| `scripts/auditar_totalizacao.py` (novo), `scripts/preparar_dados.py` | Reconciliação detalhada e integração com preparação |
| `dados/tratados/lampiadim/totalizacao_detalhada.parquet`, `referencias_totalizacao.json` (novos), `manifest.json` | Dados técnicos, referências e hashes |
| `tests/test_evolution.py`, `tests/test_evolution_ui.py` (novos) | Estatística, integridade, conversação, interface, exportação e desempenho |
| `tests/test_conversational.py`, `tests/avaliacao/referencias.json` | Expectativas atualizadas para indicadores agora disponíveis |
| `docs/EVOLUCAO_ABSTENCAO.md` (novo), `README.md` | Método, fontes, reprodução e acesso à documentação |
| `.gitignore`, `.gitattributes` | Versionamento dos derivados auditados, preservação dos bytes do JSON conferido por SHA256 e exclusão de logs locais |
| `resultados/VALIDACAO-EVOLUCAO.md` e `resultados/evolucao-*` | Relatório, exportações, evidências visuais e JUnit |

Os nomes abreviados `lampiadim/...` nessa tabela ficam sob `Lampiadim_MVP/`.
A pasta preexistente `.claude/` não foi alterada.

## Evidências para abrir

- [Interface desktop](evolucao-desktop.png), [tablet](evolucao-tablet.png) e
  [celular](evolucao-mobile.png).
- [Infográfico PNG](evolucao-eleitoral.png), [análise PDF](evolucao-eleitoral.pdf)
  e [indicadores CSV](evolucao-eleitoral.csv).
- [Renderização conferida do PDF](evolucao-pdf-verificado.png).
- [Metodologia completa](../docs/EVOLUCAO_ABSTENCAO.md).
