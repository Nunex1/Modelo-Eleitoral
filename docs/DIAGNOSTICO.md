# Diagnóstico antes da implementação — 26/10/2026

O projeto existente é Python 3.13, Pandas e Jupyter. A aplicação em
`Lampiadim_MVP/app.py` usa Streamlit; não havia API própria, serviço de IA,
testes ou configuração de hospedagem. A execução existente era local via
`python -m streamlit run`. O repositório estava sem alterações locais.

## Inventário preservado

- `analise_eleitoral.ipynb`: 23 células. Inspeção dos ZIPs, extração do primeiro
  turno presidencial, exclusão do exterior e municípios sem votos, conferência
  dos percentuais, comparação nacional e estadual, perfil por sexo e identidade,
  associação por município/UF com a planilha de DDD. Nenhuma célula é removida.
- `dados/brutos/votacao_candidato_munzona_2026.zip`: arquivos estaduais, BR e ZZ.
  O arquivo BR contém a eleição presidencial; não deve ser somado às partições.
- `dados/brutos/perfil_eleitorado_2026.zip`: partições estaduais, BR e ZZ.
  As 27 partições estaduais são mutuamente exclusivas; excluir BR/ZZ.
- `dados/brutos/base cidades completa.xlsx` e cópia no MVP: 5.571 linhas,
  13 colunas, incluindo `codigo_ibge`, `cidade`, `uf`, `ddd`, `estado`.
- `dados/tratados/resultado_presidencial_2026*.csv`: agregados do notebook.
- `Lampiadim_MVP/resultado_presidencial_2026_brasil.csv`: 66.852 linhas,
  5.571 municípios, 12 candidaturas, 118.969.906 votos nominais válidos.
- `perfil_demografico_municipios_2026.csv` e cópia no MVP: 42.378 linhas,
  157.826.587 eleitores cadastrados. Preservar a distinção entre cadastro e votação.
- `notebooks/`, `scripts/`, `resultados/`: inicialmente vazios.
- `Lampiadim_MVP.zip`: arquivo de distribuição anterior, preservado.

## Colunas verificadas

Votos consolidados: `SG_UF`, `CD_MUNICIPIO`, `NM_MUNICIPIO`, `NR_CANDIDATO`,
`NM_URNA_CANDIDATO`, `SG_PARTIDO`, `VOTOS`, `PERCENTUAL`.
Perfil consolidado: `SG_UF`, `CD_MUNICIPIO`, `NM_MUNICIPIO`, `DS_GENERO`,
`DS_IDENTIDADE_GENERO`, `QT_ELEITORES`, `IDENTIDADE_GENERO_AGRUPADA`.
Nos brutos existem também `AA_ELEICAO`, `DS_FAIXA_ETARIA`,
`DS_GRAU_ESCOLARIDADE`, `ANO_ELEICAO`, `NR_TURNO`, `DT_GERACAO` e
`QT_VOTOS_NOMINAIS_VALIDOS`. Os nomes são lidos e validados antes do uso.

## Limites e decisões

- Não há campos de comparecimento, abstenção, aptos da totalização, brancos ou
  nulos nos insumos disponíveis. Cadastro não substitui aptos/comparecimento.
- Só há o ano 2026. Não criar evolução histórica artificial.
- Disponibilidade de turno vem do arquivo bruto, nunca da data do computador.
- Sexo/identidade/idade/escolaridade filtram o cadastro, nunca os votos.
- DDD deve ser auditado contra a tabela pública da Anatel, por código IBGE.
  Ambiguidades e ausências ficam explícitas; não escolher correspondência arbitrária.
- Preservar Streamlit/Python. As instruções de scaffolding React/Sites não se
  aplicam à exigência de adaptar a arquitetura encontrada. Cloudflare Workers
  não executa esta aplicação Python; publicação exige hospedagem compatível.
- Nenhuma credencial de IA estava configurada. O modo local consulta os dados;
  a interpretação generativa opcional depende de credencial/modelo do servidor.
