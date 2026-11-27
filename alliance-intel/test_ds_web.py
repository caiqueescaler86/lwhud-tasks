import json
import unittest
from ds_web import DSReader, intelligence, csv_bytes

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

if __name__=='__main__':unittest.main()
