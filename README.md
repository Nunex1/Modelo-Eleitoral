# Lampiadim · Plataforma Brasileira de Inteligência Eleitoral

Evolução funcional do projeto **Modelo Eleitoral**, preservando Python, Pandas,
Streamlit, as bases locais e o notebook estatístico original.

## Abrir a aplicação

Na raiz do projeto, execute ` .\iniciar_lampiadim.ps1 ` e abra
<http://127.0.0.1:8501>.

Dashboard e assistente compartilham consultas reais: mapas Brasil/municípios,
comparação de candidaturas, sexo, identidade, idade, escolaridade, filtros
interdependentes, tabela pesquisável/paginada, exportação e histórico de chat na
sessão. A página inicial é **Pergunte ao Lampiadim**. A identidade usa a imagem
oficial fornecida em `image.png`, com fundo removido, rosto no cabeçalho/avatar e
favicon, sobre superfícies creme e azul-marinho. Candidaturas usam a mesma cor.

A barra lateral reúne turnos, conversas, dashboard, privacidade e informações.
O segundo turno apresenta sua pendência de integração. A política descreve o
funcionamento local e sinaliza dados do controlador que devem ser preenchidos
antes de uma publicação.

- [Diagnóstico do projeto original](docs/DIAGNOSTICO.md)
- [Instalação, execução, arquitetura, IA opcional e publicação](docs/EXECUCAO.md)
- [Validação executada e limites](resultados/VALIDACAO.md)
- [Redesign, arquivos alterados e identidade oficial](docs/REDESIGN.md)
- [Validação do redesign](resultados/VALIDACAO-REDESIGN.md)

Os derivados em `dados/tratados/lampiadim/` já estão preparados nesta máquina.
Em outra instalação, siga a preparação documentada. A IA generativa depende de
credencial/modelo no servidor; sem eles, o assistente usa consultas locais em
português. Comparecimento/abstenção e histórico de outros anos não são
fabricados quando a fonte está ausente.

## Origem: Brazilian Presidential Election Analysis

Análise estatística das eleições presidenciais brasileiras, utilizando Python e dados oficiais do Tribunal Superior Eleitoral (TSE).

## Objetivos

Investigar a distribuição geográfica dos votos, as características demográficas do eleitorado e as relações entre indicadores socioeconômicos e resultados eleitorais.

## Tecnologias

Python, Pandas, Jupyter Notebook e VS Code.

## Fontes

Tribunal Superior Eleitoral (TSE) e Instituto Brasileiro de Geografia e Estatística (IBGE).

## Metodologia

Tratamento dos dados, análise exploratória, estatística descritiva e modelagem econométrica.
