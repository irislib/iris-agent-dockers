"""Setup must be resumable without touching identities or active agents."""
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from launchers import onboarding
from runtime import chat_status, identity


class Onboarding(unittest.TestCase):
    def test_existing_pairing_requires_no_invite_or_new_messages(self):
        states={a:{'paired':True,'owner_hex':'a'*64,'service_ready':True,'bridge_ready':True} for a in ('hermes','openclaw')}
        with patch.object(onboarding,'prepare'), patch.object(onboarding,'wait_ready',side_effect=lambda a:states[a]), patch.object(onboarding,'chat') as chat, patch.object(onboarding.getpass,'getpass',side_effect=AssertionError('Must not ask again')), patch.object(onboarding,'show_status'), contextlib.redirect_stdout(io.StringIO()):
            onboarding.setup()
        self.assertEqual(chat.main.call_count,0)

    def test_owner_mismatch_fails_before_any_pairing(self):
        states={'hermes':{'paired':True,'owner_hex':'b'*64},'openclaw':{'paired':False}}
        with patch.object(onboarding,'prepare'), patch.object(onboarding,'wait_ready',side_effect=lambda a:states[a]), patch.object(onboarding,'npub_hex',return_value='a'*64), patch.object(onboarding,'chat') as chat:
            with self.assertRaisesRegex(ValueError,'different contact'):
                onboarding.setup(owner='owner')
        chat.main.assert_not_called()

    def test_one_invite_pairs_both_once(self):
        with patch.object(onboarding,'prepare'), patch.object(onboarding,'wait_ready',return_value={'paired':False}), patch.object(onboarding,'npub_hex',return_value='a'*64), patch.object(onboarding.getpass,'getpass',return_value='private-invite') as prompt, patch.object(onboarding,'chat') as chat, patch.object(onboarding,'show_status'), contextlib.redirect_stdout(io.StringIO()):
            onboarding.setup(owner='owner')
        prompt.assert_called_once()
        self.assertEqual([c.args for c in chat.main.call_args_list],[('pair','hermes'),('pair','openclaw')])
        self.assertTrue(all(c.kwargs=={'owner':'owner','invite':'private-invite'} for c in chat.main.call_args_list))

    def test_partial_setup_reuses_approved_owner_and_only_pairs_missing_agent(self):
        states={'hermes':{'paired':True,'owner_hex':'a'*64},'openclaw':{'paired':False}}
        with patch.object(onboarding,'prepare'), patch.object(onboarding,'wait_ready',side_effect=lambda a:states[a]), patch.object(onboarding,'npub_hex',return_value='a'*64), patch.object(onboarding,'hex_npub',return_value='saved-owner'), patch.object(onboarding,'chat') as chat, patch.object(onboarding,'show_status'), contextlib.redirect_stdout(io.StringIO()):
            onboarding.setup(invite='private-invite')
        chat.main.assert_called_once_with('pair','openclaw',owner='saved-owner',invite='private-invite')

    def test_existing_model_config_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);env=root/'.env';env.write_text('KAT_MODEL=kat-local\nBLOCK_HOST_IPS=203.0.113.9\n')
            original=env.read_bytes()
            with patch.object(onboarding,'ROOT',root),patch.object(onboarding,'installed_models',return_value=['kat-local']):
                self.assertEqual(onboarding.configure_model(None),'kat-local')
            self.assertEqual(env.read_bytes(),original)
            with patch.object(onboarding,'ROOT',root):
                with self.assertRaisesRegex(ValueError,'already uses'):
                    onboarding.configure_model('different-model')
            self.assertEqual(env.read_bytes(),original)

    def test_fresh_setup_selects_unique_installed_kat_without_pull(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(onboarding,'installed_models',return_value=['other','hf.co/example/KAT:Q4']):
            with patch.object(onboarding,'ROOT',Path(tmp)):
                self.assertEqual(onboarding.configure_model(None),'hf.co/example/KAT:Q4')
            env=Path(tmp)/'.env'
            self.assertIn('KAT_MODEL=hf.co/example/KAT:Q4',env.read_text())
            self.assertEqual(env.stat().st_mode&0o777,0o600)

    def test_status_readiness_is_not_delivery(self):
        result=onboarding.status_line('hermes',{'container_running':True,'paired':True,'service_ready':True,'bridge_ready':True,'counts':{'done':4},'last_delivery':'sent'})
        self.assertIn('ready',result)
        self.assertIn('receipt unconfirmed',result)
        self.assertNotIn('delivered',result)

    def test_stale_transport_cannot_look_ready(self):
        result=onboarding.status_line('hermes',{'container_running':True,'paired':True,'service_ready':False,'bridge_ready':True})
        self.assertIn('connecting',result)
        self.assertNotIn('ready',result)

    def test_missing_transport_does_not_imply_lost_pairing(self):
        result=onboarding.status_line('hermes',{'container_running':True,'transport_running':False})
        self.assertIn('chat service stopped',result)
        self.assertNotIn('not paired',result)

    def test_saved_owner_identity_roundtrips_with_checksum(self):
        for owner in ('0'*64, 'f'*64, bytes(range(32)).hex()):
            encoded=identity.hex_npub(owner)
            self.assertEqual(identity.npub_hex(encoded),owner)
            with self.assertRaises(ValueError):
                identity.npub_hex(encoded[:-1]+('q' if encoded[-1]!='q' else 'p'))

    def test_diagnostics_are_read_only_and_do_not_return_message_bodies(self):
        owner='a'*64
        def iris(*args):
            if args==('service','status'):
                return {'running':True,'account_loaded':True,'network_ready':True,'connected_servers':4}
            self.assertEqual(args,('read',owner,'--limit','20'))
            return {'chat':{'kind':'direct','chat_id':owner},'messages':[{'is_outgoing':True,'delivery':'seen','body':'PRIVATE MESSAGE'}]}
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)
            (state/'pairing.json').write_text(json.dumps({'owner_hex':owner,'chat_id':owner}))
            dbpath=state/'bridge.sqlite3'
            with sqlite3.connect(dbpath) as db:
                db.execute('CREATE TABLE jobs(status TEXT,reply TEXT)')
                db.execute('INSERT INTO jobs VALUES (?,?)',('done','PRIVATE REPLY'))
            before=dbpath.read_bytes()
            with patch.object(chat_status,'STATE',state),patch.object(chat_status,'iris',side_effect=iris),patch.object(chat_status.urllib.request,'urlopen',return_value=io.StringIO('{"paired":true}')):
                result=chat_status.collect()
            self.assertEqual(result['counts'],{'done':1})
            self.assertEqual(result['last_delivery'],'seen')
            self.assertTrue(result['service_ready'] and result['bridge_ready'])
            self.assertNotIn('PRIVATE',json.dumps(result))
            self.assertEqual(dbpath.read_bytes(),before)

if __name__=='__main__':unittest.main()
