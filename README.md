# Clareza — gerenciador financeiro pessoal

Aplicativo desktop Tauri 2, React, Django e **SQLite**. Interface em português, temas claro e escuro e identidade amarela do Clareza.

## Usar sem instalar dependências

Baixe o arquivo **Clareza-linux-x86_64.run**, permita sua execução nas propriedades do arquivo e abra-o. Ele inclui a interface, o serviço Django, o interpretador Python, SQLite e as bibliotecas gráficas empacotadas. Não é necessário instalar Python, Node, Rust, PostgreSQL ou FUSE, nem ter o código-fonte.

O arquivo fica em `dist/` após compilar. Em um terminal:

```bash
chmod +x Clareza-linux-x86_64.run
./Clareza-linux-x86_64.run
```

**Plataforma:** Linux x86_64 com ambiente gráfico. O arquivo compilado nesta máquina usa bibliotecas do Arch Linux atual; não é compatível automaticamente com distribuições antigas. A rotina em `.github/workflows/desktop-linux.yml` compila em Ubuntu 22.04 para uma base de compatibilidade mais ampla. Essa rotina precisa ser executada no GitHub; sua presença não significa que o pacote já foi validado em outras distribuições. Windows e macOS precisam de builds próprios.

O SQLite é criado automaticamente em `~/.local/share/br.local.clareza/clareza.sqlite3` (respeita `XDG_DATA_HOME`). As fotos e o perfil ficam no banco. Atualizar ou mover o aplicativo não apaga os dados. Nenhum dado do desenvolvedor vai no download. A pasta de dados pode ser alterada com `CLAREZA_DATA_DIR`.

Antes de cada abertura de um banco existente, o serviço faz backup consistente em `backups/`, mantendo os dez mais recentes. Para copiar seus dados manualmente, feche o aplicativo e copie o banco. Backups também contêm seus dados pessoais; a exclusão da conta não remove essas cópias.

## Compilar (somente para desenvolvimento)

Requisitos de compilação: Python 3.12+, Node 22, Rust e bibliotecas de desenvolvimento do Tauri 2 para Linux. Esses requisitos são para quem gera o pacote.

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-build.txt
npm --prefix frontend ci
./build-desktop.sh
```

Saídas: `dist/Clareza-linux-x86_64.run`, AppImage alternativo e `SHA256SUMS`. O arquivo `.run` executa o AppImage por extração temporária, sem FUSE. É necessário espaço temporário para a extração e um sistema gráfico Linux compatível.

Para abrir a versão compilada: `./start-desktop.sh`. Para instalar uma cópia independente da pasta do projeto no menu:

```bash
.venv/bin/python scripts/install-desktop.py
```

A cópia fica em `~/.local/share/clareza-app/`. Consulte `runtime.log` na pasta de dados em caso de erro.

## Dados da versão PostgreSQL

O banco antigo não é apagado nem vai no pacote. O conversor é uma operação local opcional, executada com o aplicativo fechado e antes de criar o SQLite definitivo:

```bash
# Apenas no ambiente antigo, que já possui psycopg.
.venv/bin/python scripts/migrate-postgres-to-sqlite.py
```

O script lê PostgreSQL na porta 55433 por padrão, aceita variáveis `POSTGRES_*`, importa para uma base temporária, confere todos os registros exportados e a integridade, e só então publica o SQLite. Recusa substituir um SQLite existente. Não depende de PostgreSQL após a conversão.

## Desenvolver a versão web

```bash
./start.sh
```

Abra **http://localhost:5173**. A API usa **http://127.0.0.1:8000/api/v1/** e o mesmo SQLite do usuário. Não há mais serviço PostgreSQL ou Docker no fluxo normal. O primeiro acesso cria um espaço vazio com categorias padrão.

## Funcionalidades

- Dashboard: ativos, passivos, patrimônio, gastos por categoria, evolução, vencimentos e planejamento.
- Contas e cartões: cadastro, edição, arquivamento, saldos mensais e visão por origem.
- Movimentações: despesas e receitas, categorias, edição, exclusão com confirmação, busca e filtros.
- Compras parceladas: divisão exata em até 120 parcelas, prévia antes de salvar, cronograma mensal e cancelamento das parcelas restantes.
- Faturas: cálculo por cartão, total manual opcional, pagamento e reabertura.
- Assinaturas: prévia obrigatória da primeira cobrança, escolha entre mês inicial e próxima recorrência, geração idempotente e projeções virtuais futuras.
- Agenda mensal: uma linha consolidada por fatura e competência; pendências anteriores ficam em uma consulta separada, fechada inicialmente.
- Metas: prazos, progresso, aportes individuais, histórico e necessidade mensal conjunta.
- Planejamento: renda menos gastos e aportes necessários; alerta de déficit e metas vencidas.
- Histórico: seleção de mês, comparação de seis meses, estados históricos de saldos e metas.

## Testes

```bash
CLAREZA_DATA_DIR=/tmp/clareza-tests .venv/bin/python backend/manage.py test finance
npm --prefix frontend test
.venv/bin/python scripts/check-desktop-runtime.py --service frontend/src-tauri/service/clareza-service/clareza-service
```

O teste Django usa um SQLite de teste separado. A suíte cobre também primeira cobrança, agenda por competência, passivos históricos, arredondamento, idempotência, projeções, faturas manuais e cancelamentos. A integração cria dados temporários, move o serviço congelado, remove o Python do PATH e verifica inicialização, autenticação, primeira cobrança, agenda mensal, parcelamento, projeção, persistência após reinício, backup e encerramento.

## Decisões importantes

- **Saldo manual:** movimentações e pagamentos não alteram automaticamente saldos. Atualize o saldo da conta para a competência desejada.
- **Aportes:** registram quanto foi destinado à meta; não criam novos ativos nem transferem dinheiro. Registre reservas como contas para incluí-las no patrimônio.
- **Faturas:** um total manual substitui a soma detalhada. O detalhamento não pode ultrapassá-lo.
- **Competência:** é selecionada explicitamente; o dia de fechamento é informativo na V1.
- **Parcelamento:** o valor informado é o total da compra. Cada parcela é um compromisso persistido na sua competência; não existe débito adicional pelo valor total.
- **Projeções:** assinaturas futuras aparecem nas análises sem criar movimentações antecipadas. Valores previstos não reduzem o patrimônio atual.
- **Modo pessoal:** acesso automático somente em loopback, com rejeição de origens externas. Não há tela de login na V1. Cada registro pertence a um usuário; `LOCAL_MODE=0` exige autenticação de sessão. Não expor este servidor de desenvolvimento na rede.
- **Sem bancos externos:** todos os dados são manuais, conforme especificação.

## Perfil e tema

Clique no nome ou na foto no topo da tela, ou no perfil no rodapé do menu, para abrir **Meu perfil**. Edite nome, e-mail, telefone e descrição; escolha ou remova a foto e clique em **Salvar alterações**. Fotos PNG/JPEG/WebP de até 5 MB são recortadas no centro e salvas no banco como PNG de 256 × 256, sem serviço externo.

Em **Aparência**, selecione **Modo claro** ou **Modo escuro**; a escolha é salva automaticamente. A exclusão exige digitar `EXCLUIR` e remove permanentemente o perfil e todos os dados financeiros daquele usuário. A aplicação permanece na tela de conta excluída até a criação explícita de um novo espaço.
