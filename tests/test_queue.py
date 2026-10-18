import re
import os
import json
import shutil
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import requests
from sqlalchemy import create_engine, event, text
from app import ROOT, create_app


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.settings = {
            'TESTING': True, 'SECRET_KEY': 'test-key',
            'DATABASE_URL': 'sqlite:///' + str(Path(self.directory.name) / 'queue.sqlite'),
            'TURSO_DATABASE_URL': '', 'TURSO_AUTH_TOKEN': '',
            'GOOGLE_CHAT_ENABLED': True, 'GOOGLE_CHAT_WEBHOOK_URL': 'https://example.com/webhook',
        }
        self.app = create_app(self.settings)
        self.client = self.app.test_client()
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.token = re.search(r'name="csrf-token" content="([^"]+)"', response.text)[1]
        self.headers = {'X-CSRF-TOKEN': self.token}

    def tearDown(self):
        self.app.extensions['queue_engine'].dispose()
        self.directory.cleanup()

    def create(self, **values):
        return self.client.post('/api/deployments', json={
            'responsible': 'Ana', 'squad': 'Web', 'url': 'https://example.com', **values,
        }, headers=self.headers)

    def change(self, record_id, **values):
        return self.client.patch(f'/api/deployments/{record_id}', json=values, headers=self.headers)

    def test_persistence_statuses_notes_and_protected_fields(self):
        result = self.create(notes='Executar migration')
        self.assertEqual(result.status_code, 201)
        record_id = result.json['id']
        self.assertEqual(result.json['status'], 'aguardando')
        with patch('app.requests.post') as notify:
            notify.return_value.status_code = 200
            for status in ('em andamento', 'finalizado', 'aguardando'):
                response = self.change(record_id, status=status, responsible='Outra pessoa')
                self.assertEqual(response.json['status'], status)
                self.assertEqual(response.json['responsible'], 'Ana')
                self.assertEqual(response.json['notes'], 'Executar migration')
            notify.assert_called_once()
        self.assertIsNone(self.change(record_id, notes='').json['notes'])
        other = create_app(self.settings)
        self.assertEqual(other.test_client().get('/api/deployments').json[0]['id'], record_id)
        other.extensions['queue_engine'].dispose()

    def test_move_delete_and_clear_finished(self):
        ids = [self.create(status=status).json['id'] for status in ('aguardando', 'em andamento', 'finalizado')]
        for record_id, direction, expected in (
            (ids[1], 'up', [ids[1], ids[0], ids[2]]),
            (ids[1], 'down', ids),
            (ids[0], 'end', [ids[1], ids[2], ids[0]]),
            (ids[0], 'down', [ids[1], ids[2], ids[0]]),
        ):
            response = self.client.patch(f'/api/deployments/{record_id}/move', json={'direction': direction}, headers=self.headers)
            self.assertEqual([record['id'] for record in response.json], expected)
            self.assertEqual([record['position'] for record in response.json], [1, 2, 3])
        self.assertEqual(self.client.delete(f'/api/deployments/{ids[1]}', headers=self.headers).json, {'deleted': 1})
        self.assertEqual(self.client.delete('/api/deployments/finished', headers=self.headers).json, {'deleted': 1})
        self.assertEqual(self.client.delete('/api/deployments/finished', headers=self.headers).json, {'deleted': 0})
        self.assertEqual(self.client.get('/api/deployments').json[0]['id'], ids[0])

    def test_validation_csrf_and_missing_records(self):
        self.assertEqual(self.client.post('/api/deployments', json={}).status_code, 419)
        self.assertEqual(self.client.post('/api/deployments', json={}, headers=self.headers).status_code, 422)
        for values in ({'url': 'javascript:alert(1)'}, {'url': 'https://'}, {'notes': ['bad']}, {'notes': 'a' * 2001}, {'responsible': ' '}, {'status': 'cancelado'}):
            self.assertEqual(self.create(**values).status_code, 422)
        record_id = self.create(notes='a' * 2000).json['id']
        self.assertEqual(self.change(record_id, status=None).status_code, 422)
        self.assertEqual(self.change(record_id, notes=12).status_code, 422)
        self.assertEqual(self.change(999999, status='finalizado').status_code, 404)
        self.assertEqual(self.client.patch(f'/api/deployments/{record_id}/move', json={'direction': 'invalid'}, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.delete('/api/deployments/999999', headers=self.headers).status_code, 404)

    def test_notifications_only_on_transition_and_failure_preserves_status(self):
        record_id = self.create().json['id']
        with patch('app.requests.post') as notify:
            notify.return_value.status_code = 200
            self.change(record_id, status='finalizado')
            self.change(record_id, status='finalizado')
            self.change(record_id, notes='Nova observação')
            notify.assert_called_once()
            self.assertIn('Ana', notify.call_args.kwargs['json']['text'])
            self.change(record_id, status='aguardando')
            notify.side_effect = requests.ConnectionError()
            self.assertEqual(self.change(record_id, status='finalizado').json['status'], 'finalizado')
        self.app.config['GOOGLE_CHAT_ENABLED'] = False
        with patch('app.requests.post') as notify:
            self.change(record_id, status='aguardando')
            self.change(record_id, status='finalizado')
            notify.assert_not_called()

    def test_rate_limit_is_shared_between_instances(self):
        for _ in range(60):
            self.assertEqual(self.create().status_code, 201)
        other = create_app(self.settings)
        client = other.test_client()
        client.get('/')
        with client.session_transaction() as state:
            token = state['csrf_token']
        self.assertEqual(client.post('/api/deployments', json={}, headers={'X-CSRF-TOKEN': token}).status_code, 429)
        other.extensions['queue_engine'].dispose()

    def test_concurrent_creates_have_distinct_positions(self):
        self.client.get('/api/deployments')
        def create_record(_):
            with self.app.test_client() as client:
                with client.session_transaction() as state:
                    state['csrf_token'] = 'concurrent-token'
                return client.post('/api/deployments', json={
                    'responsible': 'Ana', 'squad': 'Web', 'url': 'https://example.com',
                }, headers={'X-CSRF-TOKEN': 'concurrent-token'}).status_code
        with ThreadPoolExecutor(max_workers=4) as executor:
            self.assertEqual(list(executor.map(create_record, range(8))), [201] * 8)
        self.assertEqual([record['position'] for record in self.client.get('/api/deployments').json], list(range(1, 9)))

    def test_existing_laravel_sqlite_records_are_preserved(self):
        database = Path(self.directory.name) / 'queue.sqlite'
        with sqlite3.connect(database) as connection:
            connection.execute('''CREATE TABLE deployments (
                id INTEGER PRIMARY KEY AUTOINCREMENT, responsible VARCHAR(100) NOT NULL,
                squad VARCHAR(100) NOT NULL, url VARCHAR(2048) NOT NULL,
                status VARCHAR(30) NOT NULL, created_at DATETIME, updated_at DATETIME,
                notes TEXT, position INTEGER NOT NULL DEFAULT 0
            )''')
            connection.execute('''INSERT INTO deployments VALUES (
                7, 'Ana', 'Web', 'https://example.com', 'aguardando',
                '2026-10-17 20:00:00', '2026-10-17 20:00:00', 'Preservar', 7
            )''')
        connection.close()
        records = self.client.get('/api/deployments').json
        self.assertEqual(records[0]['id'], 7)
        self.assertEqual(records[0]['notes'], 'Preservar')
        self.assertEqual(records[0]['created_at'], '2026-10-17T20:00:00Z')
        self.assertEqual(self.create().json['position'], 8)
        self.assertEqual(self.change(7, notes='Atualizada').json['notes'], 'Atualizada')

    def test_turso_configuration_and_transactions_use_remote_driver(self):
        engine = create_engine(self.settings['DATABASE_URL'], connect_args={'isolation_level': None})
        statements = []
        @event.listens_for(engine, 'before_cursor_execute')
        def capture_sql(connection, cursor, statement, parameters, context, many):
            statements.append(statement)
        settings = self.settings | {
            'TURSO_DATABASE_URL': 'libsql://queue-test.turso.io',
            'TURSO_AUTH_TOKEN': 'fake-token',
        }
        with patch('app.create_engine', return_value=engine) as factory:
            remote = create_app(settings)
        self.assertEqual(factory.call_args.args[0], 'sqlite+libsql://queue-test.turso.io?secure=true')
        self.assertEqual(factory.call_args.kwargs['connect_args'], {'auth_token': 'fake-token', 'isolation_level': None})
        client = remote.test_client()
        self.assertEqual(client.get('/up').status_code, 200)
        client.get('/')
        with client.session_transaction() as state:
            token = state['csrf_token']
        response = client.post('/api/deployments', json={
            'responsible': 'Ana', 'squad': 'Web', 'url': 'https://example.com',
        }, headers={'X-CSRF-TOKEN': token})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(client.get('/api/deployments').json[0]['id'], response.json['id'])
        with self.assertRaises(RuntimeError):
            with engine.begin() as connection:
                connection.execute(text("UPDATE deployments SET notes='rollback'"))
                raise RuntimeError('Rollback')
        self.assertIsNone(client.get('/api/deployments').json[0]['notes'])
        self.assertIn('BEGIN IMMEDIATE', statements)
        self.assertNotIn('PRAGMA busy_timeout=10000', statements)
        engine.dispose()

    def test_turso_requires_complete_credentials_and_valid_url(self):
        for values in (
            {'TURSO_DATABASE_URL': 'libsql://test.turso.io'},
            {'TURSO_AUTH_TOKEN': 'fake-token'},
            {'TURSO_DATABASE_URL': 'http://test.turso.io', 'TURSO_AUTH_TOKEN': 'fake-token'},
            {'TURSO_DATABASE_URL': 'libsql://test.turso.io?authToken=secret', 'TURSO_AUTH_TOKEN': 'fake-token'},
        ):
            with self.subTest(values=values), self.assertRaises(RuntimeError):
                create_app(self.settings | values)

    def test_vercel_rejects_local_sqlite(self):
        with patch.dict(os.environ, {'VERCEL': '1', 'SECRET_KEY': 'test-secret'}):
            with self.assertRaisesRegex(RuntimeError, 'TURSO_DATABASE_URL'):
                create_app(self.settings | {'TESTING': False})

    def test_built_assets_work_without_public_directory_in_function(self):
        manifest = json.loads((ROOT / 'resources/views/assets.json').read_text(encoding='utf-8'))
        entry = manifest['resources/js/app.js']
        bundle_root = Path(self.directory.name) / 'function'
        shutil.copytree(ROOT / 'resources/views', bundle_root / 'resources/views')
        self.assertFalse((bundle_root / 'public').exists())
        with patch('app.ROOT', bundle_root):
            page = self.client.get('/')
            for filename, mime in [(entry['file'], 'javascript')] + [(name, 'text/css') for name in entry.get('css', [])]:
                self.assertIn('/build/' + filename, page.text)
                with self.client.get('/build/' + filename) as response:
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(mime, response.content_type)
                    self.assertGreater(len(response.data), 100)
            self.assertEqual(self.client.get('/build/assets/missing.js').status_code, 404)


if __name__ == '__main__':
    unittest.main()
