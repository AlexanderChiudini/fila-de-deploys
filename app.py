"""Deploy Queue: Flask API and the existing Vue interface."""

import hashlib
import json
import os
import secrets
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, render_template_string, request, send_from_directory, session
from sqlalchemy import Column, Integer, MetaData, String, Table, Text, create_engine, delete, event, insert, select, text, update
from sqlalchemy.pool import NullPool

load_dotenv(encoding='utf-8-sig')
ROOT = Path(__file__).resolve().parent
STATUSES = ('aguardando', 'em andamento', 'finalizado')
metadata = MetaData()
deployments = Table(
    'deployments', metadata,
    Column('id', Integer, primary_key=True),
    Column('responsible', String(100), nullable=False),
    Column('squad', String(100), nullable=False),
    Column('url', String(2048), nullable=False),
    Column('status', String(30), nullable=False),
    Column('notes', Text),
    Column('position', Integer, nullable=False),
    Column('created_at', String(40), nullable=False),
    Column('updated_at', String(40), nullable=False),
)
rate_limits = Table(
    'python_rate_limits', metadata,
    Column('key', String(64), primary_key=True),
    Column('window', Integer, nullable=False),
    Column('count', Integer, nullable=False),
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def notify_finished(record: dict, application: Flask) -> None:
    url = application.config['GOOGLE_CHAT_WEBHOOK_URL']
    if not application.config['GOOGLE_CHAT_ENABLED'] or not url:
        return
    message = '\n'.join([
        f"Deploy #{record['id']} finalizado", f"Responsável: {record['responsible']}",
        f"Squad: {record['squad']}", f"Link: {record['url']}",
        f"Observação: {record['notes'] or 'Não informada'}",
        f"Fila: {application.config['APP_URL']}",
    ])
    try:
        response = requests.post(url, json={'text': message}, timeout=(2, 5), allow_redirects=False)
        if not 200 <= response.status_code < 300:
            application.logger.warning('Falha ao notificar deploy #%s no Google Chat.', record['id'])
    except requests.RequestException:
        application.logger.warning('Não foi possível conectar ao Google Chat (deploy #%s).', record['id'])


def validate(data: object, creating: bool = False, moving: bool = False) -> tuple[dict, dict]:
    if not isinstance(data, dict):
        data = {}
    fields = {'direction': 10} if moving else ({'responsible': 100, 'squad': 100, 'url': 2048} if creating else {}) | {'status': 30, 'notes': 2000}
    required = {'direction'} if moving else {'responsible', 'squad', 'url'} if creating else set()
    clean, errors = {}, {}
    for field, maximum in fields.items():
        if field not in data and field not in required:
            continue
        value = data.get(field)
        if isinstance(value, str):
            value = value.strip() or None
        valid = (value is None and field == 'notes') or (isinstance(value, str) and len(value) <= maximum)
        if field == 'status':
            valid = value in STATUSES
        if field == 'direction':
            valid = value in ('up', 'down', 'end')
        if field == 'url' and valid:
            try:
                parsed = urlsplit(value)
                valid = parsed.scheme in ('http', 'https') and bool(parsed.hostname) and not any(c.isspace() for c in value)
                parsed.port
            except ValueError:
                valid = False
        if valid:
            clean[field] = value
        else:
            errors[field] = ['Informe um valor válido para este campo.']
    return clean, errors


def create_app(settings: dict | None = None) -> Flask:
    application = Flask(__name__, static_folder=None)
    application.config.update(
        SECRET_KEY=os.getenv('SECRET_KEY') or os.getenv('APP_KEY') or secrets.token_hex(32),
        DATABASE_URL=os.getenv('DATABASE_URL', f'sqlite:///{ROOT / "database/database.sqlite"}'),
        TURSO_DATABASE_URL=os.getenv('TURSO_DATABASE_URL', ''),
        TURSO_AUTH_TOKEN=os.getenv('TURSO_AUTH_TOKEN', ''),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=bool(os.getenv('VERCEL')),
        MAX_CONTENT_LENGTH=64 * 1024,
        GOOGLE_CHAT_ENABLED=os.getenv('GOOGLE_CHAT_ENABLED', '').lower() in ('true', '1', 'yes'),
        GOOGLE_CHAT_WEBHOOK_URL=os.getenv('GOOGLE_CHAT_WEBHOOK_URL', ''),
        APP_URL=os.getenv('APP_URL', 'http://localhost:8000'),
    )
    application.config.update(settings or {})
    database_url = application.config['DATABASE_URL']
    turso_url = application.config['TURSO_DATABASE_URL'].strip()
    turso_token = application.config['TURSO_AUTH_TOKEN'].strip()
    engine_options = {'poolclass': NullPool}
    if turso_url:
        parsed = urlsplit(turso_url)
        if parsed.scheme != 'libsql' or not parsed.hostname or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username:
            raise RuntimeError('TURSO_DATABASE_URL deve ter o formato libsql://seu-banco.turso.io.')
        if not turso_token:
            raise RuntimeError('Configure TURSO_AUTH_TOKEN para conectar ao Turso.')
        database_url = f'sqlite+libsql://{parsed.netloc}?secure=true'
        engine_options['connect_args'] = {'auth_token': turso_token, 'isolation_level': None}
    elif turso_token:
        raise RuntimeError('Configure TURSO_DATABASE_URL junto com TURSO_AUTH_TOKEN.')
    elif not database_url.startswith('sqlite:///'):
        raise RuntimeError('Use DATABASE_URL com SQLite local ou configure as variáveis TURSO_DATABASE_URL e TURSO_AUTH_TOKEN.')
    if os.getenv('VERCEL') and not application.testing:
        if not turso_url:
            raise RuntimeError('Configure TURSO_DATABASE_URL e TURSO_AUTH_TOKEN na Vercel.')
        if not (os.getenv('SECRET_KEY') or os.getenv('APP_KEY')):
            raise RuntimeError('Configure SECRET_KEY na Vercel.')
    engine = create_engine(database_url, **engine_options)
    if not turso_url:
        @event.listens_for(engine, 'connect')
        def sqlite_connect(connection, _) -> None:
            connection.isolation_level = None
            connection.execute('PRAGMA busy_timeout=10000')

    @event.listens_for(engine, 'begin')
    def sqlite_begin(connection) -> None:
        connection.exec_driver_sql('BEGIN IMMEDIATE')

    @contextmanager
    def transaction():
        with engine.begin() as connection:
            yield connection

    initialized = False

    def initialize_database() -> None:
        nonlocal initialized
        if not initialized:
            with transaction() as connection:
                metadata.create_all(connection)
            initialized = True

    application.extensions['queue_engine'] = engine

    @application.before_request
    def protect_writes():
        if request.path.startswith('/api/'):
            initialize_database()
            if request.method in ('POST', 'PATCH', 'DELETE'):
                token = request.headers.get('X-CSRF-TOKEN', '')
                if not token or not secrets.compare_digest(token, session.get('csrf_token', '')):
                    return jsonify(message='Sua sessão expirou.'), 419
                limit = 120 if request.method == 'PATCH' else 60
                identity = request.remote_addr or 'unknown'
                key = hashlib.sha256(f'{identity}:{request.method}'.encode()).hexdigest()
                window = int(time.time()) // 60
                with transaction() as connection:
                    connection.execute(delete(rate_limits).where(rate_limits.c.window < window))
                    current = connection.execute(select(rate_limits).where(rate_limits.c.key == key)).mappings().first()
                    if current and current['count'] >= limit:
                        return jsonify(message='Muitas requisições. Tente novamente em um minuto.'), 429
                    if current:
                        connection.execute(update(rate_limits).where(rate_limits.c.key == key).values(count=current['count'] + 1))
                    else:
                        connection.execute(insert(rate_limits).values(key=key, window=window, count=1))

    @application.after_request
    def prevent_api_caching(response):
        if request.path.startswith('/api/') or request.path == '/':
            response.headers['Cache-Control'] = 'no-store'
        return response

    @application.errorhandler(404)
    def not_found(_):
        return jsonify(message='Registro não encontrado.'), 404

    @application.get('/')
    def index():
        session.setdefault('csrf_token', secrets.token_hex(32))
        manifest = json.loads((ROOT / 'resources/views/assets.json').read_text(encoding='utf-8'))
        entry = manifest['resources/js/app.js']
        return render_template_string(
            (ROOT / 'resources/views/queue.html').read_text(encoding='utf-8'),
            csrf_token=session['csrf_token'], script='/build/' + entry['file'],
            styles=['/build/' + path for path in entry.get('css', [])],
        )

    @application.get('/build/<path:filename>')
    def assets(filename: str):
        return send_from_directory(ROOT / 'resources/views/build', filename)

    @application.get('/up')
    def health():
        initialize_database()
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
        return jsonify(status='ok')

    def ordered(connection) -> list[dict]:
        records = connection.execute(select(deployments).order_by(deployments.c.position, deployments.c.id)).mappings()
        return [serialize(record) for record in records]

    def serialize(record) -> dict:
        result = dict(record)
        for field in ('created_at', 'updated_at'):
            value = result[field]
            if isinstance(value, datetime):
                result[field] = value.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')
            elif isinstance(value, str) and 'T' not in value:
                result[field] = value.replace(' ', 'T') + 'Z'
        return result

    def find(connection, deployment_id: int) -> dict:
        record = connection.execute(select(deployments).where(deployments.c.id == deployment_id)).mappings().first()
        if record is None:
            abort(404)
        return serialize(record)

    @application.route('/api/deployments', methods=['GET', 'POST'], strict_slashes=False)
    def collection():
        if request.method == 'GET':
            with engine.connect() as connection:
                return jsonify(ordered(connection))
        data, errors = validate(request.get_json(silent=True), creating=True)
        if errors:
            return jsonify(message='Confira os campos informados.', errors=errors), 422
        with transaction() as connection:
            records = ordered(connection)
            stamp = now()
            result = connection.execute(insert(deployments).values(
                **({'status': 'aguardando', 'notes': None} | data),
                position=max((record['position'] for record in records), default=0) + 1,
                created_at=stamp, updated_at=stamp,
            ))
            record = find(connection, result.inserted_primary_key[0])
        return jsonify(record), 201

    @application.delete('/api/deployments/finished')
    def clear_finished():
        with transaction() as connection:
            result = connection.execute(delete(deployments).where(deployments.c.status == 'finalizado'))
        return jsonify(deleted=result.rowcount)

    @application.route('/api/deployments/<int:deployment_id>', methods=['PATCH', 'DELETE'])
    def detail(deployment_id: int):
        finished = False
        with transaction() as connection:
            record = find(connection, deployment_id)
            if request.method == 'DELETE':
                connection.execute(delete(deployments).where(deployments.c.id == deployment_id))
                return jsonify(deleted=1)
            data, errors = validate(request.get_json(silent=True))
            if errors:
                return jsonify(message='Confira os campos informados.', errors=errors), 422
            finished = record['status'] != 'finalizado' and data.get('status') == 'finalizado'
            if data:
                connection.execute(update(deployments).where(deployments.c.id == deployment_id).values(**data, updated_at=now()))
            record = find(connection, deployment_id)
        if finished:
            notify_finished(record, application)
        return jsonify(record)

    @application.patch('/api/deployments/<int:deployment_id>/move')
    def move(deployment_id: int):
        with transaction() as connection:
            find(connection, deployment_id)
            data, errors = validate(request.get_json(silent=True), moving=True)
            if errors:
                return jsonify(message='Confira os campos informados.', errors=errors), 422
            records = ordered(connection)
            index = next(index for index, record in enumerate(records) if record['id'] == deployment_id)
            target = {'up': max(0, index - 1), 'down': min(len(records) - 1, index + 1), 'end': len(records) - 1}[data['direction']]
            records.insert(target, records.pop(index))
            for position, record in enumerate(records, 1):
                connection.execute(update(deployments).where(deployments.c.id == record['id']).values(position=position, updated_at=now()))
            result = ordered(connection)
        return jsonify(result)

    return application


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '8000')))
