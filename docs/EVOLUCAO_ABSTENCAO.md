# Evolução entre turnos, comparecimento e votos não válidos

Implementação integrada ao Lampiadim, eleição presidencial de 2026. A seção
principal aparece no início de **Resultados eleitorais** ao selecionar o segundo
turno. O primeiro turno mantém comparecimento, abstenção, brancos/nulos e uma
opção explícita de comparação. Os demais recursos e o histórico da sessão são
preservados.

## Contrato de evidência

- **DADO OFICIAL:** contagens de arquivos do TSE, com turno, território, fonte,
  geração na origem e SHA256.
- **CÁLCULO ESTATÍSTICO:** razões, diferenças, rankings e decomposição, obtidos
  sobre essas contagens. Não são explicações causais.
- **SIMULAÇÃO HIPOTÉTICA:** transporte entre categorias condicionado a premissas;
  nunca é migração observada, probabilidade individual ou intervalo de confiança.

Não há cruzamento de voto com sexo, identidade de gênero, idade ou escolaridade.
Esses filtros continuam a atuar sobre o cadastro e o simulador demográfico;
os indicadores eleitorais oficiais permanecem referentes ao território completo.
Logs de urna continuam separados das candidaturas e suas limitações de cobertura
continuam vigentes.

## Fontes e granularidade

Fontes de controle: [Dados Abertos TSE](https://dadosabertos.tse.jus.br/dataset/resultados-2026)
e [Divulgação de Resultados](https://resultados.tse.jus.br/oficial/app/index.html).
Eleição 6257 identifica o primeiro turno; 6258, o segundo.

`votos.parquet` tem a granularidade ano + turno + UF + município TSE + número da
candidatura. O consolidado prevalece; `votos_divulgacao.parquet` só supre períodos
ausentes. `totalizacao.parquet` tem uma linha por ano + turno + UF + município
TSE, inclusive localidades do exterior (`ZZ`). Não se misturam agregados de UF
com linhas municipais.

`scripts/auditar_totalizacao.py` relê os JSONs brutos e produz:

- `totalizacao_detalhada.parquet`: mesmas chaves, contagens técnicas, URL,
  geração e SHA256 de cada JSON.
- `referencias_totalizacao.json`: contagens de controle de cada UF e Brasil,
  nota sobre TTE e verificações remotas opcionais.

Todos os campos obrigatórios precisam existir: vazio ou `null` não vira zero.
Na carga são conferidos os hashes. Em consulta são conferidos esquema, chaves,
cobertura, totalização final, não negatividade, integralidade, somas nominais,
identidades de contagem e controles oficiais por UF.

## Reconciliação e categorias técnicas

Conferências executadas sobre os dois turnos:

1. Soma de municípios = controle da UF, para todas as contagens preparadas.
2. Soma de UFs + exterior = controle nacional.
3. Soma de candidaturas = votos válidos, em cada município brasileiro.
4. Comparecimento = válidos + brancos + nulos totais.
5. Nulos totais (`tvn`) = nulos de urna (`vn`) + nulos técnicos (`vnt`).
6. Aptos publicados = comparecimento + abstenção + aptos das categorias de
   seções não instaladas/não apuradas, quando a definição permite essa identidade.

São preservados separadamente `van`, `vansj`, `vsan` e `vscv`. Essas variáveis
não são adicionadas automaticamente ao comparecimento: algumas categorias podem
ser subconjuntos. Uma definição nova que não reconcilie bloqueia a análise.

### Nota dos 39 registros e exterior

A página de Dados Abertos informa **158.745.502 registros** e **158.745.463
eleitores efetivos**, após considerar 39 duplicidades de transferência
temporária. O ajuste nacional é idempotente: nunca se subtrai 39 de cada
município, de cada UF, de cada parcela ou de um total já ajustado.

Os JSONs consultados também contêm **423 aptos em seções não instaladas**, no
exterior, com comparecimento e abstenção zerados nessas localidades. Logo, o
eleitorado nacional publicado não é igual a comparecimento + abstenção. O ajuste
de 39 não elimina nem explica sozinho essa diferença.

O painel territorial usa **Brasil sem exterior** por padrão, sempre identificado.
Mantém os aptos territoriais publicados, pois a nota não fornece a localização
dos duplicados. A referência nacional com exterior aparece em Metodologia e
fontes. O assistente aceita explicitamente Brasil com exterior e exterior.
Nas taxas nacionais com exterior, o denominador é o efetivo documentado; a
composição fechada e a matriz de fluxos ficam bloqueadas, pois não há alocação
defensável da correção entre as categorias técnicas.

Isso é uma limitação da identificação territorial, não uma licença para
reclassificar registros. Os totais, versões e diferenças ficam visíveis.

## Fórmulas e unidades

Cada turno usa seu próprio universo. Agregações somam contagens **antes** de
calcular taxas. Não há média simples de taxas municipais rotulada como taxa
estadual ou nacional.

| Indicador | Denominador |
|---|---|
| Participação de candidato | Votos válidos do turno |
| Comparecimento e abstenção | Eleitorado apto do turno |
| Brancos, nulos e brancos + nulos | Comparecimento do turno |
| Composição do eleitorado | Aptos do turno, quando as categorias fecham |
| Crescimento relativo | Quantidade inicial |

Variação absoluta = final - inicial. Variação relativa = 100 × diferença /
inicial. Variação de taxa = taxa final - taxa inicial, em pontos percentuais.
Divisão por zero fica **indisponível**, sem infinito nem zero artificial.
Mediana/P10/P90 são quantis não ponderados das localidades e estão rotulados.

### Decomposição da evolução de Lula

Se `L1 = V1*p1` e `L2 = V2*p2`:

```
participação = (p2 - p1) * (V1 + V2) / 2
base válida  = (V2 - V1) * (p1 + p2) / 2
participação + base válida = L2 - L1
```

O motor usa `Fraction`, sem erro de arredondamento intermediário. Só a
apresentação arredonda. A cascata não mede a origem dos votos nem um efeito causal.

## Laboratório de hipóteses

São seis origens e cinco destinos, sem "demais candidatos" no segundo turno.
Antes de calcular, o sistema exige categorias exaustivas, mesma abrangência,
mesmo total de aptos nos dois turnos e declaração explícita da hipótese de
composição constante. Totais iguais não comprovam identidade das pessoas.

O modelo de transporte usa `scipy.optimize.linprog` (HiGHS), já disponível no
ambiente científico do projeto. Restrições: somas de linhas e colunas iguais às
margens observadas, não negatividade, retenções mínimas dos dois finalistas,
parcelas opcionais fixas de demais candidatos/abstenção destinadas a Lula e
limites de brancos/nulos destinados a votos válidos.

O objetivo pode maximizar permanência nas categorias, demais candidatos → Lula
ou abstenção → Lula. É uma escolha exploratória; pode selecionar um vértice
extremo do conjunto viável e não é estimador de trajetórias reais. Fluxos são
massas fracionárias hipotéticas; não se arredondam para indivíduos artificiais.
A tolerância de conservação é `1e-5` voto, sem tolerância relativa.

Sensibilidade: três retenções mínimas de Lula (base e +/- 10 p.p., truncadas aos
limites) e três objetivos. Cenários inviáveis permanecem rotulados e sem Sankey.
Limites sem restrições adicionais são `max(0, origem+destino-total)` e
`min(origem,destino)`. Dois problemas lineares também calculam limites
condicionais de demais candidatos → Lula. Nenhum desses intervalos é intervalo
de confiança.

Nos snapshots auditados, os aptos diferem entre turnos no Brasil sem exterior
(-149), em Americana (-2) e em Campinas (-47). Por isso, nesses recortes há
comparação oficial e explicação, **sem matriz artificial**. Em municípios com
margens fechadas, o laboratório pode operar sob declaração hipotética.

## Filtros, assistente e exportações

Região, UF, DDD validado e município atuam em conjunto. Alterar os filtros
visíveis atualiza o contexto do chat e conserva suas mensagens. Perguntas
explícitas podem escolher outro território; perguntas de continuação herdam o
contexto. Intenções novas usam `consultar_indicadores`; limitações sobre migração
e horários têm prioridade sobre a interpretação por IA externa.

CSV preserva contagens, taxas, variações, denominadores, versão, fontes e notas.
PNG e PDF são produzidos localmente com Pillow, sem Chrome, CDN ou envio de
dados. PDF traz a prancha consolidada e até 20 linhas do ranking selecionado,
com critério de ordenação explícito; o CSV contém o ranking inteiro. O cenário
tem exportações separadas com premissas e aviso permanente.

**Limite de acessibilidade do PDF:** as páginas são rasterizadas; use a tabela
acessível da interface ou CSV para leitura estruturada/seleção de texto. Os
gráficos da interface têm descrições e tabelas, além de rótulos que não dependem
exclusivamente das cores. Para mapas municipais extensos, filtre uma UF; os
rankings completos continuam disponíveis.

## Reproduzir

```powershell
.\.venv\Scripts\python.exe scripts\preparar_dados.py --divulgacao
.\.venv\Scripts\python.exe scripts\auditar_totalizacao.py --verificar-remoto
.\.venv\Scripts\python.exe -m pytest -q
```

A preparação chama a auditoria local automaticamente. A opção remota verifica
Brasil, Americana e Campinas em ambos os turnos e aborta em caso de mudança.
Atualizações de origem exigem nova coleta e preparação; não há fallback de
produção para dados fictícios. Cache é vinculado à instância dos dados e à versão
do manifesto; não há releitura de Parquet por interação.
