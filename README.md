# Deploy Queue

Fila compartilhada com **Laravel 13 (PHP 8.3+) e Vue 3**. Interface em português, responsiva, com cadastro de responsável, squad e URL; status `aguardando`, `em andamento` e `finalizado`; busca, filtros, contadores e atualização automática a cada 10 segundos. Banco real compartilhado entre visitantes; sem login.

## Executar localmente

Requisitos: PHP 8.3+ com extensões do Laravel e PDO SQLite, Composer 2 e Node.js 22.

```sh
composer install
cp .env.example .env
php artisan key:generate
```

No Windows, use `Copy-Item .env.example .env` para copiar o arquivo. Crie `database/database.sqlite` vazio (`New-Item database/database.sqlite -ItemType File` no PowerShell ou `touch database/database.sqlite` no Linux).

```sh
php artisan migrate
npm ci
npm run build
php artisan serve
```

Abra http://localhost:8000. Para desenvolver o Vue, rode `npm run dev` em outro terminal.

## Executar com Docker

Copie `.env.example` para `.env`. Gere uma chave:

```sh
docker run --rm php:8.4-cli-alpine php -r "echo 'base64:'.base64_encode(random_bytes(32)).PHP_EOL;"
```

Cole a saída em `APP_KEY` do `.env` e execute:

```sh
docker compose up --build -d
```

Abra http://localhost:8080. O volume `deploy_data` preserva o SQLite entre reinícios e atualizações. Não remova esse volume se quiser manter os registros.

## Publicar em uma URL

O Dockerfile permite publicar o projeto em um serviço com containers e volume persistente, como Render ou Railway. O servidor incluído é adequado a uma fila interna de baixo tráfego; para alta demanda use PHP-FPM/Nginx, FrankenPHP ou Laravel Octane.

1. Envie este projeto para um repositório Git.
2. Crie um serviço Docker apontando para o repositório e para o `Dockerfile` da raiz.
3. Configure `APP_KEY` (gere como acima), `APP_URL=https://seu-dominio`, `APP_ENV=production` e `APP_DEBUG=false`.
4. Para SQLite, monte um disco persistente em `/data`, com escrita para o usuário do container. Use apenas uma instância. `DB_CONNECTION=sqlite` e `DB_DATABASE=/data/database.sqlite` já são os padrões do container.
5. Publique. As migrations rodam automaticamente na inicialização; `/up` é o endpoint de saúde.

Alternativamente use PostgreSQL gerenciado: configure `DB_CONNECTION=pgsql`, `DB_HOST`, `DB_PORT=5432`, `DB_DATABASE`, `DB_USERNAME`, `DB_PASSWORD` e `DB_SSLMODE=require` (conforme o provedor). Nesse caso não é necessário um volume para os registros. Mantenha a mesma `APP_KEY` em novos deploys. Quando estiver atrás de um proxy HTTPS, configure os proxies confiáveis em `bootstrap/app.php` conforme seu provedor, sem confiar indiscriminadamente em qualquer proxy.

### Sobre a Vercel

Este projeto entrega Vue e Laravel na mesma origem, sem CORS. O caminho disponibilizado é Docker: a Vercel não executa esse container PHP diretamente. Hospede o projeto completo em uma plataforma compatível com PHP/Docker. Separar o Vue na Vercel exigiria hospedar a API Laravel em outro serviço e adaptar sessão/CSRF/CORS; essa separação não é necessária para esta aplicação.

## Uso e permissões

Qualquer visitante com a URL pode cadastrar registros e alterar o status de qualquer registro. Sem autenticação, o sistema não verifica quem é o responsável. O responsável usa o seletor de status ao lado do seu deploy. Há proteção CSRF, validação no servidor e limite de requisições de escrita; links aceitam apenas HTTP/HTTPS. Não há bloqueio automático de deploys simultâneos: a fila organiza visualmente os registros em ordem de criação. Se duas pessoas alterarem o mesmo registro ao mesmo tempo, prevalece a última alteração salva.

## Verificação

```sh
php artisan test
npm run build
```

Testes cobrem cadastro, persistência dos três status, ordem da fila, validação, URLs inválidas, registros inexistentes e proteção dos demais campos durante alteração de status.

## API (mesma origem, sessão e CSRF)

- `GET /api/deployments`: lista por ordem de criação.
- `POST /api/deployments`: `responsible`, `squad`, `url`, `status` opcional (padrão `aguardando`).
- `PATCH /api/deployments/{id}`: altera somente `status`.

As rotas de escrita exigem o token CSRF da página. Dados ficam na tabela `deployments`.