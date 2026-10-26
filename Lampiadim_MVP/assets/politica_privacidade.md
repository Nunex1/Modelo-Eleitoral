### 1. Quem é responsável

Lampiadim é o nome desta plataforma de consulta a dados eleitorais. **A identidade do controlador ainda não foi informada.** Antes da publicação, preencher: nome ou razão social, identificação aplicável, endereço de contato e identificação do encarregado, quando aplicável. O nome da plataforma não substitui esses dados.

**Canal de privacidade: pendente de definição pelo responsável.** Não há e-mail ou formulário de atendimento configurado nesta versão. O canal efetivo para solicitações precisa ser informado antes de disponibilizar o serviço ao público.

### 2. Quais dados são tratados

- **Perguntas e conversas:** o texto digitado, as respostas, o título da conversa e seu contexto de consulta ficam no estado da sessão no servidor. Uma pergunta pode conter dados pessoais se você os inserir. Não envie CPF, endereço, telefone, informações sigilosas ou dados pessoais de terceiros.
- **Filtros e preferências de navegação:** município, UF, DDD, ano, turno, candidatura e categorias demográficas selecionadas são usados para executar as consultas e manter o contexto durante a sessão. A aplicação não deduz sua opinião política a partir dessas escolhas.
- **Dados eleitorais públicos:** resultados agregados por território, nomes públicos das candidaturas e contagens cadastrais por categoria. A plataforma não recebe nomes, CPF ou registros individuais de eleitores e não identifica o voto de uma pessoa. O cruzamento de categorias descreve contagens, sem identificar eleitores.
- **Dados técnicos:** a conexão ao servidor envolve metadados de rede, como endereço IP. Servidor, proxy ou provedor de hospedagem podem manter registros técnicos. A hospedagem pública, seus registros e seus prazos ainda não foram definidos.

Não há cadastro de usuário, login, pagamento, envio de documentos ou coleta de localização precisa nesta versão.

### 3. Finalidades e bases legais

As informações fornecidas são usadas para interpretar a pergunta, consultar as bases locais, apresentar resultados, manter o contexto e permitir baixar ou remover conversas da sessão. Os dados técnicos necessários à conexão suportam o funcionamento e a segurança do serviço.

**As bases legais de cada operação ainda precisam ser definidas e documentadas pelo controlador**, à luz dos arts. 7º e 11 da LGPD, quando aplicáveis. Esta política não presume consentimento pelo simples acesso, nem declara legítimo interesse sem a avaliação correspondente. Se houver tratamento que dependa de consentimento, seu mecanismo deverá ser implementado antes da ativação. A versão pública depende dessas definições.

### 4. Consultas locais e inteligência artificial externa

O modo de consulta em uso aparece no início desta página e na barra lateral. No modo local, perguntas são interpretadas no próprio servidor e não são enviadas ao serviço de IA. As consultas usam arquivos já preparados; conversar não dispara downloads no TSE, IBGE ou Anatel.

Se o responsável configurar a integração com a **OpenAI**, a aplicação enviará a pergunta atual e os filtros de contexto para interpretação. Não envia o histórico completo, as tabelas de resultados ou os arquivos eleitorais brutos nessa requisição. Os cálculos continuam sendo executados localmente. O pedido de não armazenar a resposta (`store=false`) está configurado; isso não equivale a uma garantia de ausência de todos os registros mantidos pelo fornecedor.

Antes de ativar essa integração em uma publicação, o responsável deve verificar e informar as condições contratuais, a retenção do fornecedor, os locais de processamento e o mecanismo aplicável a eventual transferência internacional. Esses detalhes ainda não foram documentados para o Lampiadim. O chat não é um canal para enviar dados pessoais sensíveis.

### 5. Compartilhamento e serviços de terceiros

Não há funcionalidade de venda de dados, publicidade comportamental ou publicação das conversas. O compartilhamento com a OpenAI ocorre somente quando a integração está habilitada, conforme descrito acima. Uma hospedagem futura poderá envolver operadores de infraestrutura, que precisam ser identificados pelo responsável.

Os links para TSE, IBGE, Anatel, Planalto e ANPD levam a sites externos, sujeitos às respectivas políticas. Um arquivo baixado por você passa a estar sob sua guarda e não é apagado pelo controle de exclusão de conversas.

### 6. Armazenamento, retenção e exclusão

O histórico é mantido na memória da sessão do Streamlit; o código da aplicação não o grava em banco de dados ou arquivo de histórico. Recarregar a página ou perder a sessão pode interromper o acesso às conversas. Isso não é uma promessa de apagamento imediato de memória, logs, cópias de infraestrutura ou registros de fornecedores.

O botão **“Apagar conversas da sessão”** remove as conversas acessíveis da sessão atual e inicia uma conversa vazia. **“Nova conversa” não apaga o histórico anterior.** Arquivos que você baixou, registros externos e eventuais logs da infraestrutura não são eliminados por esses botões.

**Os prazos de retenção e os procedimentos de exclusão de logs, backups e dados de fornecedores estão pendentes de definição.** Não foi estabelecido um prazo universal de guarda nesta versão. Essas informações devem ser completadas antes da publicação.

### 7. Seus direitos

Conforme a LGPD e as condições aplicáveis, você pode solicitar confirmação e acesso, correção, informação sobre compartilhamentos, anonimização, bloqueio ou eliminação, portabilidade, revogação de consentimento e informações sobre sua recusa. Também pode se opor a tratamento irregular e solicitar revisão de decisões exclusivamente automatizadas que afetem seus interesses. A plataforma oferece consultas estatísticas e não toma decisões individuais sobre seus direitos.

As solicitações devem ser encaminhadas ao canal do controlador, **ainda pendente de preenchimento**. Consulte as [orientações da ANPD sobre direitos dos titulares](https://www.gov.br/anpd/pt-br/assuntos/titular-de-dados-1/direito-dos-titulares) para conhecer as condições de exercício e de petição à autoridade. A publicação exige um canal de atendimento efetivo.

### 8. Medidas de segurança existentes

O código mantém credenciais no ambiente do servidor, limita o tamanho das perguntas, valida parâmetros de consulta e não permite que o modelo execute SQL ou código. Verifica a integridade dos arquivos preparados e mantém o histórico no estado da sessão. A telemetria de uso do Streamlit está desativada na configuração do projeto. O inicializador local escuta apenas no endereço de loopback.

Não há autenticação nesta versão. HTTPS público, controle de acesso administrativo, política de logs, backups, resposta a incidentes e outras medidas da hospedagem precisam ser definidos e verificados antes da publicação. Não afirmamos que existam certificações, criptografia de histórico em repouso ou proteção absoluta contra incidentes.

### 9. Cookies e tecnologias semelhantes

O aplicativo não instala ferramentas de publicidade ou análise de audiência. O Streamlit pode usar cookies técnicos, como o de proteção contra requisições indevidas, e recursos do navegador necessários à interface e à conexão. O estado principal das conversas está no servidor, vinculado à sessão.

A política final deve identificar os cookies e tecnologias efetivamente usados na hospedagem escolhida, suas finalidades e durações. Caso sejam adicionados recursos não essenciais, o responsável deverá avaliar e implementar os controles apropriados antes de ativá-los. Não há banner de consentimento fictício nesta versão.

### 10. Atualizações e referência legal

**Última atualização: 26 de outubro de 2026.** Esta página descreve a implementação local atual e explicita os campos que dependem do responsável pela publicação. Deve ser revisada quando houver mudanças no tratamento, nos fornecedores ou na infraestrutura.

Referência: [Lei nº 13.709/2018 — Lei Geral de Proteção de Dados Pessoais](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm). Esta minuta técnica não representa uma declaração de conformidade jurídica integral.
