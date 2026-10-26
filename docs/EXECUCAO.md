# Executar e manter o Lampiadim

## Iniciar no Windows

Na raiz `Modelo Eleitoral`, execute:

```powershell
.\iniciar_lampiadim.ps1
```

Abra <http://127.0.0.1:8501>. O chat é a página inicial. Dashboard, privacidade e
informações estão na barra lateral. As rotas também podem ser abertas diretamente:
`?pagina=dashboard`, `?pagina=privacidade` e `?pagina=sobre`.
Alternativa sem script PowerShell:

```powershell
.\.venv\Scripts\python.exe -m streamlit run Lampiadim_MVP/app.py --server.address 127.0.0.1 --server.port 8501
```

Dependências da aplicação, separadas do ambiente de análise já existente:

```powershell
.\.venv\Scripts\python.exe -m pip install -r Lampiadim_MVP/requirements.txt
```

Em outro computador, extraia `resultados/Lampiadim-local.zip` e crie primeiro o
ambiente com `python -m venv .venv` (Python 3.13). O pacote contém os derivados
prontos para abrir o painel; os ZIPs brutos necessários para reprocessamento
devem ser copiados separadamente do projeto original.

## Reproduzir a preparação

```powershell
.\.venv\Scripts\python.exe scripts/preparar_dados.py
```

O script exige os ZIPs já existentes em `dados/brutos/`, a planilha e os CSVs
originais em `Lampiadim_MVP/`. Lê as 27 partições estaduais do cadastro e apenas
o arquivo BR da votação presidencial. Não soma BR com UFs. Normaliza os códigos
TSE para cinco dígitos, incluindo os zeros iniciais que o notebook havia removido.
Reconcilia todos os grupos do cadastro original e cada município/candidatura do
primeiro turno. Preserva insumos e notebook.

A preparação acessa Anatel e IBGE por HTTPS; a aplicação pronta usa arquivos
locais, sem necessidade desses serviços a cada interação. Mapas não usam tiles
nem CDN. Os arquivos derivados ficam em `dados/tratados/lampiadim/`; seus hashes,
fontes, datas de geração, partições e pendências ficam em `manifest.json`.
O carregamento da aplicação confere os hashes dos três Parquets.

Para atualizar geografia sem reprocessar o perfil, após uma preparação concluída:

```powershell
.\.venv\Scripts\python.exe scripts/preparar_dados.py --skip-profile
```

Para gerar somente os metadados de candidaturas (nome completo, partido, situação
na totalização e votos no exterior) sobre uma preparação concluída:

```powershell
.\.venv\Scripts\python.exe scripts/preparar_dados.py --only-candidates
```

Esse modo lê apenas o arquivo BR do ZIP de votação, reconcilia com `votos.parquet`
e exige que os demais derivados estejam íntegros.

### Segundo turno e totalização (portal de divulgação)

Enquanto o arquivo consolidado do TSE não traz o 2º turno, os resultados vêm do
portal oficial de divulgação. A coleta é retomável e respeita um limite de
requisições (`RPS`, padrão 5 por segundo; `WORKERS`, padrão 8):

```powershell
.\.venv\Scripts\python.exe -I scripts/baixar_divulgacao.py 6258 6257
.\.venv\Scripts\python.exe -I scripts/preparar_dados.py --divulgacao
```

`6258` é o 2º turno e `6257` o 1º. A preparação só aceita coletas completas,
reconcilia municípios × UF × Brasil e confere que o 1º turno da divulgação é
idêntico ao `votos.parquet`. Gera `votos_divulgacao.parquet`,
`totalizacao.parquet` e as linhas do 2º turno em `candidatos.parquet`.

### Horários das urnas (logs)

```powershell
.\.venv\Scripts\python.exe -I scripts/coletar_logs_urna.py 3221 --municipios sp:61310 sp:62910 --amostra 150
.\.venv\Scripts\python.exe -I scripts/coletar_logs_urna.py 3220 --municipios sp:61310 sp:62910
.\.venv\Scripts\python.exe -I scripts/preparar_dados.py --horarios
```

`3221` é o pleito do 2º turno e `3220` o do 1º; `--municipios` usa `uf:código
TSE` e `--amostra` sorteia seções do Brasil para a validação cruzada. A
preparação também lê o `secoes.csv` do urnas-tardias fixado por commit em
`dados/brutos/urnas_tardias/`. Gera `horarios_secoes.parquet` e
`horarios_faixas.parquet`. Um município só entra quando todas as suas seções
foram coletadas. A metodologia está em
[SEGUNDO_TURNO_HORARIOS_SIMULACAO.md](SEGUNDO_TURNO_HORARIOS_SIMULACAO.md).

`--divulgacao` e `--horarios` reconstroem só os próprios derivados e exigem que
os demais estejam íntegros. Uma preparação completa executa os dois.

O modo `--skip-profile` exige o mesmo hash do ZIP cadastral. Faça atualizações com a aplicação
parada; o script substitui os derivados e grava o manifesto ao final. Uma falha
na preparação é explícita e pode exigir reexecução antes de iniciar o painel.
Não edite Parquets manualmente. As pastas de dados continuam ignoradas pelo Git,
como no projeto original; em outro computador copie os insumos e prepare-os, ou
use o pacote de distribuição com os derivados incluídos.

## Assistente

Arquitetura, ferramentas, contexto, regras estatísticas, testes e limites estão
em [INTELIGENCIA_CONVERSACIONAL.md](INTELIGENCIA_CONVERSACIONAL.md).

O modo local não é um modelo generativo. Ele interpreta a pergunta (intenção,
entidades, filtros, métrica, referências ao contexto), executa consultas tipadas
e verificadas e responde por modelos determinísticos. Mantém o contexto da
conversa e pede esclarecimento quando a ambiguidade muda o resultado. Há perguntas
sugeridas, nova conversa, histórico da sessão e download. Uma atualização completa
da página ou o encerramento da sessão pode apagar o histórico. Cada sessão é
independente; não existe armazenamento global de chats.

A integração opcional usa a Responses API da OpenAI com *function calling*
estrito: o modelo escolhe a ferramenta e os argumentos, e o servidor revalida,
calcula e redige. Configure no **ambiente do servidor**, antes da execução:

- `OPENAI_API_KEY`: sua credencial, mantida fora do código e do Git.
- `OPENAI_MODEL`: identificador de um modelo habilitado na conta com suporte a
  Structured Outputs. Não há modelo presumido ou selecionado automaticamente.

Não coloque credenciais em perguntas, URLs ou arquivos distribuídos. A aplicação
envia ao provedor a pergunta, o contexto estruturado (entidades em foco, sem texto
de mensagens anteriores) e a lista pública de candidaturas. Os registros
eleitorais não são enviados. Usa `store=false` e timeout de 20 segundos. A resposta do modelo
nunca é executada como código/SQL. Quantidades, percentuais e tabelas são
calculados pelo serviço Python local. Falhas do provedor acionam o modo local e
são identificadas na resposta, sem expor detalhes de credenciais.

Referência do contrato implementado:
<https://developers.openai.com/api/docs/guides/function-calling>.
A conexão com um provedor real não foi testada: não havia credencial/modelo
configurados. Os testes verificam o contrato e o tratamento de falhas com
respostas controladas; isso não equivale a homologação externa.

## Testes

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q --junitxml=resultados/testes-lampiadim.xml
.\.venv\Scripts\python.exe scripts\avaliar_lampiadim.py
```

Os testes exigem os dados preparados reais. Cobrem reconciliação integral,
denominadores, interseções, DDD, CSV reaberto, homônimos, contexto, ausência de
dados, isolamento entre voto e perfil, contrato de IA e navegação Streamlit.
A inteligência conversacional tem suíte própria (`tests/test_conversational.py`)
e avaliação por conjunto de referência (`scripts/avaliar_lampiadim.py`).
Consulte `resultados/VALIDACAO.md` e `resultados/VALIDACAO-INTELIGENCIA.md` para
o que foi efetivamente executado.

## Arquitetura

- `Lampiadim_MVP/app.py`: composição da interface e estado da sessão.
- `Lampiadim_MVP/lampiadim/data.py`: filtros tipados, validação, consultas,
  denominadores e exportação. Dashboard e chat compartilham esse contrato.
- `Lampiadim_MVP/lampiadim/assistant.py`: orquestra as camadas do assistente.
  `interpreter.py` (intérprete local), `llm.py` (OpenAI opcional), `entities.py`
  (entidades verificadas), `context.py` e `planner.py` (contexto e
  esclarecimentos), `tools.py` (ferramentas tipadas), `engine.py` (motor
  estatístico), `verification.py` (verificação) e `responses.py` (respostas pt-BR).
- `Lampiadim_MVP/lampiadim/charts.py`: gráficos Plotly e mapas IBGE em Mercator.
- `Lampiadim_MVP/lampiadim/branding.py`: carregamento local da identidade oficial.
- `Lampiadim_MVP/assets/`: ilustração oficial com transparência, versões WebP/SVG,
  estilos centralizados, política de privacidade e malhas.
- `scripts/preparar_dados.py`: preparação e linhagem reexecutáveis.
- `scripts/baixar_divulgacao.py` e `scripts/coletar_logs_urna.py`: coleta
  retomável dos resultados divulgados e dos logs das urnas.
- `analise_eleitoral.ipynb`: análises anteriores, preservadas.

## Publicação

Não houve publicação externa. É uma aplicação Python/Streamlit; requer servidor
compatível, memória para o cadastro agregado e suporte a WebSocket. O Dockerfile
incluído usa os mesmos arquivos locais preparados. Exemplo em máquina com Docker:

```powershell
docker build -t lampiadim .
docker run --rm -p 127.0.0.1:8501:8501 lampiadim
```

O container usa usuário sem privilégios. Não copia ambiente virtual, arquivos
brutos, credenciais ou histórico Git. O build Docker não foi executado nesta
entrega. Para expor o serviço externamente, configure domínio, HTTPS e política
de acesso no provedor escolhido; o launcher local permanece em loopback.
Complete a identidade e o contato do controlador, as bases legais, os prazos de
retenção e as condições dos fornecedores na política antes da publicação.

## Limitações dos insumos

- Somente 2026. O 1º turno vem do ZIP consolidado; o 2º, do portal de
  divulgação, até o TSE publicar o consolidado. Outros anos não são fabricados.
- Comparecimento, abstenção e aptos vêm da totalização divulgada pelo TSE.
  `QT_ELEITORES` é cadastro e não substitui esses denominadores.
- A distribuição por faixa horária só existe onde a linha do tempo completa foi
  coletada (Americana e Campinas). Os logs contam 158.149 votos a menos que o
  comparecimento oficial do 2º turno (0,12%): urnas substituídas e seções sem log.
- Os horários nunca são atribuídos a candidaturas; os logs não registram a escolha.
- DDD validado em 5.561 de 5.571 municípios. Dez pendências estão no manifesto
  e no painel. Associações duvidosas não são escolhidas automaticamente.
- Nove grafias divergentes da planilha foram resolvidas por coincidência exata
  de nome normalizado/UF na tabela Anatel, com código IBGE existente na planilha.
- Malha simplificada IBGE: 5.570 geometrias; quatro localidades eleitorais não
  possuem vínculo nominal IBGE e a malha não inclui Boa Esperança do Norte.
  Essas localidades permanecem nos totais nacionais e nas tabelas.
- Todos os 645 municípios paulistas têm vínculo IBGE e DDD validado.
- Os arquivos TSE do usuário foram reconciliados localmente, sem alegação de
  sincronização em tempo real ou conferência de checksum com o download TSE atual.
- As análises são descritivas. Não identificam voto individual nem causalidade.
