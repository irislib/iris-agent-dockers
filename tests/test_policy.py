import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
os.environ['KAT_MODEL']='test-local-kat'
from model_gate import validate
from guard import rules
from broker import incoming, validate_chat
from pair import npub_hex

class ModelPolicy(unittest.TestCase):
    def test_only_installed_model_and_inference(self):
        for method,path in [('POST','/api/pull'),('DELETE','/api/delete'),('POST','/api/create'),('GET','http://host:8080/'),('POST','/api/chat?target=other')]:
            with self.subTest(path=path),self.assertRaises(ValueError): validate(method,path,{'model':'test-local-kat'})
        with self.assertRaises(ValueError): validate('POST','/api/chat',{'model':'other','messages':[]})
        self.assertEqual(validate('POST','/api/chat',{'model':'test-local-kat','messages':[]})['options']['num_ctx'],65536)
    def test_context_and_output_bounded(self):
        result=validate('POST','/api/chat',{'model':'test-local-kat','messages':[],'options':{'num_ctx':1000000,'num_predict':-1}})
        self.assertEqual(result['options'],{'num_ctx':65536,'num_predict':4096})

class ContactPolicy(unittest.TestCase):
    def test_only_approved_direct_conversation(self):
        owner='a'*64
        for chat in ({'kind':'group','chat_id':owner},{'kind':'direct','chat_id':'b'*64},{}):
            with self.assertRaises(ValueError): validate_chat(chat,owner)
        validate_chat({'kind':'direct','chat_id':owner},owner)
    def test_untrusted_message_fields_cannot_route(self):
        good={'chat_id':'a'*64,'is_outgoing':False,'body':'Hello'}
        self.assertTrue(incoming(good,'a'*64))
        for bad in ({**good,'chat_id':'b'*64},{**good,'is_outgoing':True},{**good,'deleted_for_everyone':True},{**good,'body':''}):
            self.assertFalse(incoming(bad,'a'*64))
    def test_recipient_injection_rejected_before_iris(self):
        from broker import complete
        with patch('broker.iris') as cli:
            with self.assertRaises(ValueError): complete({'job_id':'1','text':'hello','recipient':'other'})
            cli.assert_not_called()
    def test_invalid_npub_rejected(self):
        for value in ['npub1bad','0'*64,'npub1'+'q'*58]:
            with self.assertRaises(ValueError):npub_hex(value)

class NetworkPolicy(unittest.TestCase):
    def test_exception_is_only_ollama_gate_port(self):
        text=rules(['8.8.8.8'])
        self.assertIn(':OUTPUT DROP',text)
        self.assertIn('-d 172.30.240.2 -p tcp --dport 11434 -j ACCEPT',text)
        self.assertIn('-d 8.8.8.8/32 -j REJECT',text)
        self.assertLess(text.index('-d 10.0.0.0/8'),text.index('-A OUTPUT -j ACCEPT'))
        self.assertLess(text.index('-d 100.64.0.0/10'),text.index('-A OUTPUT -j ACCEPT'))
        self.assertLess(text.index('-d 224.0.0.0/4'),text.index('-A OUTPUT -j ACCEPT'))


class DurableReplies(unittest.TestCase):
    def test_duplicate_completion_sends_once_and_keeps_owner(self):
        import broker
        with tempfile.TemporaryDirectory() as tmp, patch.object(broker,'STATE',Path(tmp)):
            owner='a'*64
            (Path(tmp)/'pairing.json').write_text(json.dumps({'owner_hex':owner,'chat_id':owner}))
            with broker.connect() as db:
                db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?)',('job1','task','running',1,None,None))
            calls=[]
            def cli(*args,**kwargs):
                calls.append(args)
                if args[0]=='read': return {'chat':{'kind':'direct','chat_id':owner},'messages':[]}
                if args[0]=='send': return {'message':{'id':'sent1','delivery':'queued'}}
                raise AssertionError(args)
            with patch.object(broker,'iris',cli):
                first=broker.complete({'job_id':'job1','text':'Done'})
                second=broker.complete({'job_id':'job1','text':'Done'})
            self.assertEqual(first['message_id'],second['message_id'])
            self.assertEqual([c for c in calls if c[0]=='send'],[('send',owner,'Done')])
    def test_ambiguous_send_recovers_from_history_without_resending(self):
        import broker
        with tempfile.TemporaryDirectory() as tmp, patch.object(broker,'STATE',Path(tmp)):
            owner='a'*64
            (Path(tmp)/'pairing.json').write_text(json.dumps({'owner_hex':owner,'chat_id':owner}))
            with broker.connect() as db:
                db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?)',('job1','task','reply_pending',1,'Done',None))
            with patch.object(broker,'iris',return_value={'chat':{'kind':'direct','chat_id':owner},'messages':[{'id':'existing','is_outgoing':True,'body':'Done','created_at_secs':3}]}) as cli:
                result=broker.complete({'job_id':'job1','text':'Done'})
            self.assertEqual(result['message_id'],'existing')
            self.assertEqual(cli.call_count,1)

if __name__=='__main__': unittest.main()
