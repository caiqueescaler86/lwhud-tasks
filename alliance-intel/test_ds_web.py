import json
import unittest
from ds_web import DSReader, DSDatabaseReader, intelligence, csv_bytes, safe_reader_error

class Response:
    def __init__(self,value):self.value=value
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,n):return json.dumps(self.value).encode()

class DSWebTests(unittest.TestCase):
    def test_read_scope_and_cache(self):
        calls=[]
        def mock(req,timeout):
            calls.append((req.full_url,req.headers,json.loads(req.data)))
            if 'auth/v1' in req.full_url:return Response({'access_token':'test-jwt','expires_in':3600})
            return Response([{'match':{'starters':[]}}])
        r=DSReader('https://example.supabase.co','sb_publishable_fake','test@example.com','pass',opener=mock)
        a=r.read();a[0]['match']['starters'].append('bad')
        self.assertEqual(r.read(),[{'match':{'starters':[]}}]);self.assertEqual(len(calls),2)
        self.assertEqual(calls[1][1]['Authorization'],'Bearer test-jwt')
        self.assertTrue(calls[1][0].endswith('/rpc/lw_ds_read'))
    def test_reject_untrusted_host_and_secret_key(self):
        with self.assertRaises(ValueError):DSReader('https://evil.com','sb_publishable_fake','x','y')
        with self.assertRaises(ValueError):DSReader('https://example.supabase.co','sb_secret_fake','x','y')
    def test_threat_and_unknown(self):
        row={'match':{'starters':[{'hero_power':100}]},'enemy':{'status':'worst','top':[{'hero_power':120}]}}
        self.assertEqual(intelligence(row)['threats'],[{'hero_power':120}])
        self.assertEqual(intelligence({'match':{'starters':[]}})['status'],'generic')

    def test_database_reader_scope_cache(self):
        calls=[]
        class Cursor:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def execute(self,sql):calls.append(sql)
            def fetchall(self):return [({'match':{'starters':[]}},)]
        class Connection:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def cursor(self):return Cursor()
        def connect(dsn,**kw):
            self.assertEqual(kw['sslmode'],'verify-full')
            self.assertEqual(kw['connect_timeout'],8)
            return Connection()
        r=DSDatabaseReader('postgresql://lw_ds_streamlit_reader.test:fake@aws-0-us-east-1.pooler.supabase.com:5432/postgres',connector=connect)
        a=r.read();a[0]['match']['starters'].append('changed')
        self.assertEqual(r.read(),[{'match':{'starters':[]}}])
        self.assertEqual(len(calls),2)
        self.assertIn('lw_ds_private.matches',calls[1])
        self.assertIn('LIMIT 8',calls[1])
    def test_database_reader_reject_admin_and_untrusted_host(self):
        for dsn in ('postgresql://postgres.test:fake@aws-0-us-east-1.pooler.supabase.com:5432/postgres',
                    'postgresql://lw_ds_streamlit_reader.test:fake@evil.com:5432/postgres',
                    'postgresql://lw_ds_streamlit_reader.test:fake@aws-0-us-east-1.pooler.supabase.com:5432/postgres?sslmode=disable'):
            with self.assertRaises(ValueError):DSDatabaseReader(dsn)

    def test_safe_reader_errors_do_not_leak_credentials(self):
        class DatabaseError(Exception):
            sqlstate="42501"
        examples=[
            (ValueError("credential-sentinel-8927"),False,"DS-CONFIG-MISSING"),
            (ImportError("credential-sentinel-8927"),True,"DS-DRIVER"),
            (RuntimeError("password authentication failed: credential-sentinel-8927"),True,"DS-AUTH"),
            (DatabaseError("credential-sentinel-8927"),True,"DS-PERMISSION"),
            (RuntimeError("certificate verify failed: credential-sentinel-8927"),True,"DS-TLS"),
            (RuntimeError("connection refused: credential-sentinel-8927"),True,"DS-NETWORK"),
            (ValueError("credential-sentinel-8927"),True,"DS-CONFIG-OR-RESPONSE"),
        ]
        for exc,configured,prefix in examples:
            result=safe_reader_error(exc,configured)
            self.assertTrue(result.startswith(prefix))
            self.assertNotIn("credential-sentinel-8927",result.lower())


if __name__=='__main__':unittest.main()
