"""Exercise real HTTP auth, multipart persistence, restore and revision conflicts."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
import unittest

import requests


@unittest.skipUnless(shutil.which('php'), 'PHP CLI required (provided by CI)')
class ScoreApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)/'account'
        docroot = cls.root/'www'
        repo = Path(__file__).resolve().parents[1]
        for relative in ['data-manager/api','johny/api']:
            shutil.copytree(repo/'site'/relative, docroot/'test'/relative)
        private = cls.root/'stocktool-private'
        private.mkdir()
        cls.key = 'test-only-not-a-real-secret-1234567890'
        (private/'config.php').write_text("<?php return ['api_key'=>'"+cls.key+"'];",encoding='utf-8')
        with closing(socket.socket()) as sock:
            sock.bind(('127.0.0.1',0))
            port = sock.getsockname()[1]
        cls.base = f'http://127.0.0.1:{port}/test/johny/api/'
        cls.process = subprocess.Popen(['php','-d','upload_max_filesize=128M','-d','post_max_size=160M',
            '-S',f'127.0.0.1:{port}','-t',str(docroot)], stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                requests.get(cls.base+'state.php',timeout=.5)
                break
            except requests.ConnectionError:
                time.sleep(.05)
        else:
            cls.process.terminate()
            cls.temp.cleanup()
            raise RuntimeError('PHP test server did not start')
        cls.database = cls.root/'test.sqlite'
        with closing(sqlite3.connect(cls.database)) as connection:
            connection.execute('CREATE TABLE test(value TEXT)')
            connection.commit()

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=10)
        cls.temp.cleanup()

    def call(self, query, **kwargs):
        return requests.get(self.base+'state.php?'+query,
                            headers={'X-StockTool-Key':self.key},timeout=5,**kwargs)

    def publish(self, revision, *, database=None, result=None):
        result = result or {'schema_version':1, 'generated_at':'2026-11-15T12:00:00Z',
                          'run_id':1,'signals':[{'ticker':'AAA'}], 'metadata':{},
                          'learning':{'status':'NOT_ENOUGH_DATA'}}
        with (database or self.database).open('rb') as file:
            return requests.post(self.base+'publish.php',headers={'X-StockTool-Key':self.key},
                data={'expected_revision':revision,'result':json.dumps(result)},
                files={'database':('history.sqlite',file,'application/octet-stream')},timeout=5)

    def test_atomic_roundtrip_conflict_and_auth(self):
        self.assertEqual(requests.get(self.base+'state.php',timeout=5).status_code,401)
        self.assertEqual(requests.post(self.base+'publish.php',timeout=5).status_code,401)
        self.assertEqual(self.call('kind=manifest').json()['revision'],'empty')
        first = self.publish('empty')
        self.assertEqual(first.status_code,200,first.text)
        revision = first.json()['revision']
        manifest = self.call('kind=manifest').json()
        self.assertEqual(manifest['revision'],revision)
        database = self.call('kind=database&revision='+revision)
        self.assertEqual(database.content,self.database.read_bytes())
        self.assertEqual(hashlib.sha256(database.content).hexdigest(),manifest['database_sha256'])
        result = self.call('kind=results').json()
        self.assertTrue(result['ok'])
        self.assertEqual(result['signals'][0]['ticker'],'AAA')
        self.assertEqual(self.publish('empty').status_code,409)
        self.assertEqual(self.call('kind=manifest').json()['revision'],revision)
        bad = self.root/'bad.sqlite'
        bad.write_bytes(b'x'*200)
        self.assertEqual(self.publish(revision,database=bad).status_code,422)
        self.assertEqual(self.call('kind=manifest').json()['revision'],revision)
        second = self.publish(revision)
        self.assertEqual(second.status_code,200,second.text)
        self.assertEqual(len(self.call('kind=history').json()['runs']),2)
        self.assertEqual(self.call('kind=results&revision='+revision).json()['revision'],revision)
        self.assertEqual(self.call('kind=database&revision=..%2Fconfig.php').status_code,422)
        # Database resides outside the document root, so no public URL can expose it.
        public = requests.get(self.base.replace('/test/johny/api/','/')+'stocktool-private/johny/'+revision+'/history.sqlite',timeout=5)
        self.assertEqual(public.status_code,404)
