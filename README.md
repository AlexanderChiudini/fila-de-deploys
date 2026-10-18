# Deploy Queue

Fila compartilhada com **Python 3.13, Flask e Vue 3**, preparada para Vercel. Mantém a interface em português, busca, filtros, contadores por status, atualização a cada 10 segundos, observações, reordenação, exclusão individual e limpeza de finalizados. As notificações opcionais do Google Chat continuam sendo enviadas somente na transição para finalizado; falhas no webhook não desfazem a alteração.

## Executar localmente

Requisitos: Python 3.13 e Node.js 22.

```sh
python -m venv .venv
```

Ative o ambiente: `.venv\Scripts\Activate.ps1` no PowerShell ou `source .venv/bin/activate` no Linux/macOS.

```sh
pip install -r requirements.txt
```

Copie `.env.example` para `.env` (`Copy-Item .env.example .env` no Windows). Gere uma chave com `python -c "import secrets; print(secrets.token_hex(32))"` e coloque em `SECRET_KEY`.

```sh
npm ci
npm run build
python app.py
```

Abra http://localhost:8000. A tabela é criada automaticamente no primeiro acesso à API. O SQLite existente em `database/database.sqlite` é reutilizado, preservando seus registros. O `.env` antigo também funciona localmente: `APP_KEY` é aceito como alternativa a `SECRET_KEY`. A aplicação Python não depende de PHP, Composer ou Artisan. Após editar a interface, rode `npm run build` novamente.

## Publicar na Vercel

1. Envie as alterações ao seu repositório e importe o projeto na Vercel usando a raiz deste diretório.
2. Selecione o preset **Flask**. O `vercel.json` configura o build `npm ci && npm run build`; remova eventuais overrides antigos de PHP ou de diretório de saída no painel. O ponto de entrada é `app.py`.
3. Crie um banco Turso (libSQL/SQLite) e configure `TURSO_DATABASE_URL=libsql://seu-banco.turso.io` e `TURSO_AUTH_TOKEN` com um token de leitura e escrita. Essas variáveis têm prioridade sobre `DATABASE_URL`.
4. Configure `SECRET_KEY` com uma chave aleatória estável e `APP_URL` com a URL pública. Configure também essas variáveis em Preview caso utilize esse ambiente; prefira um banco separado para Preview.
5. Para notificações, configure `GOOGLE_CHAT_ENABLED=true` e `GOOGLE_CHAT_WEBHOOK_URL` com seu webhook. Sem essas variáveis, as notificações ficam desativadas.
6. Publique. `/up` verifica a conexão com o banco. As tabelas são criadas automaticamente no primeiro acesso; o token precisa permitir escrita e criação de tabelas.

```dotenv
TURSO_DATABASE_URL=libsql://seu-banco.turso.io
TURSO_AUTH_TOKEN=seu-token
SECRET_KEY=sua-chave-aleatoria
APP_URL=https://seu-projeto.vercel.app
```

A aplicação usa a conexão remota HTTPS do driver oficial `sqlalchemy-libsql`, sem criar réplicas ou arquivos SQLite na Vercel. O banco Turso mantém a fila compartilhada entre instâncias e publicações. Não é necessário PostgreSQL. Remova a antiga variável PostgreSQL `DATABASE_URL` do painel; as variáveis Turso passam a controlar a conexão.

Para obter as credenciais pela CLI do Turso:

```sh
turso db show --url nome-do-banco
turso db tokens create nome-do-banco
```

Não inclua o token no Git nem em variáveis `VITE_*`: ele é utilizado somente no servidor. Os registros do SQLite local não são enviados automaticamente ao Turso; um banco novo começa vazio.

Sem as variáveis Turso, o desenvolvimento local continua usando `database/database.sqlite`. Para testar com Turso no Windows, use o container Docker: o driver nativo oficial é compatível com Linux/macOS. O arquivo `requirements.txt` instala esse driver nesses ambientes, incluindo a Vercel, e mantém a instalação local Windows com SQLite padrão.

## Docker

Defina `SECRET_KEY` no `.env` e execute:

```sh
docker compose up --build -d
```

Abra http://localhost:8080. O volume `deploy_data` mantém o SQLite em `/data/database.sqlite`. O container usa Python/Gunicorn. Se definir `TURSO_DATABASE_URL` e `TURSO_AUTH_TOKEN` no `.env`, ele conecta ao Turso em vez do arquivo local. Não remova o volume se quiser preservar os registros.

## Uso e API

Qualquer visitante com a URL pode cadastrar e alterar registros, sem login. O sistema organiza visualmente a fila; não bloqueia deploys simultâneos. Escritas exigem o token CSRF da página e possuem limites compartilhados no banco (60/minuto para POST e DELETE, 120/minuto para PATCH, por IP/método). Atrás de proxies, o limite usa o endereço fornecido pelo servidor WSGI e pode agrupar visitantes. URLs aceitam HTTP/HTTPS. As mutações são serializadas por transação para preservar a ordem da fila.

- `GET /api/deployments`: lista por posição e ID.
- `POST /api/deployments`: responsável (`responsible`), squad, URL, status opcional e observações (`notes`).
- `PATCH /api/deployments/{id}`: altera somente status e/ou observações.
- `PATCH /api/deployments/{id}/move`: direção (`direction`) `up`, `down` ou `end`.
- `DELETE /api/deployments/{id}`: exclui um registro.
- `DELETE /api/deployments/finished`: exclui os finalizados.

Status: `aguardando`, `em andamento`, `finalizado`. Os contadores continuam sendo calculados pelo Vue usando a lista completa, independentemente da busca e do filtro.

## Verificação

```sh
npm run build
python -m unittest discover -s tests -p "test_*.py" -v
```

Os testes Python cobrem persistência, concorrência no SQLite, status, observações, ordem, exclusões, validação, CSRF, limite compartilhado e notificações com falhas simuladas. Não enviam mensagens reais. O projeto usa somente Python e Vue; os arquivos e dependências do Laravel foram removidos.

Os testes também verificam configuração do Turso, credenciais incompletas, proteção contra SQLite efêmero na Vercel e rollback de transações usando SQLite como substituto do banco remoto. A conexão real ao Turso exige suas credenciais e não é exercitada por esses testes.
