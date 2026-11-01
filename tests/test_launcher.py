"""Launcher routing checks never start, stop or replace real containers."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('agents_cli', str(ROOT / 'agents'))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)


class Routing(unittest.TestCase):
    def test_setup_and_chat_status_never_target_opencode(self):
        with patch.object(cli.opencode, 'main', side_effect=AssertionError('OpenCode must stay untouched')), patch.object(cli.onboarding, 'setup', return_value=0) as setup, patch.object(cli.onboarding, 'show_status', return_value=0) as status:
            self.assertEqual(cli.main(['setup']), 0)
            self.assertEqual(cli.main(['chat-status']), 0)
        setup.assert_called_once_with(None, owner=None, invite=None, model=None)
        status.assert_called_once_with(('hermes', 'openclaw'))

    def test_shortcuts_preserve_literal_terminal_arguments(self):
        with patch.object(cli.chat, 'main', return_value=0) as chat:
            cli.main(['hermes', '--', '-lc', 'printf "%s" "$(literal)"'])
        self.assertEqual(chat.call_args.args, ('shell', 'hermes'))
        self.assertEqual(chat.call_args.kwargs['shell_args'], ['-lc', 'printf "%s" "$(literal)"'])
        with patch.object(cli.opencode, 'main', return_value=0) as oc:
            cli.main(['opencode', '--workspace', 'experiment'])
        oc.assert_called_once_with(['shell', '--workspace', 'experiment'])

    def test_status_all_routes_once_to_each_backend(self):
        with patch.object(cli.opencode, 'main', return_value=0) as oc, patch.object(cli.chat, 'main', return_value=0) as chat:
            cli.main(['status'])
        oc.assert_called_once_with(['status', '--workspace', 'default'])
        chat.assert_called_once_with('status')

    def test_workspace_rejected_for_chat_agents(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            cli.main(['shell', 'hermes', '--workspace', 'not-supported'])
        self.assertEqual(error.exception.code, 2)

    def test_targeted_stop_leaves_other_agent_and_model_gate_running(self):
        with patch.object(cli.chat, 'compose') as compose:
            cli.chat.main('stop', 'hermes')
        compose.assert_called_once_with('stop', 'hermes', 'hermes-iris', 'hermes-net')

    def test_start_never_replaces_existing_containers(self):
        with patch.object(cli.chat, 'compose') as compose:
            cli.chat.main('up', 'openclaw')
        compose.assert_called_once_with('up', '-d', '--no-recreate', 'model-gate', 'openclaw-net', 'openclaw-iris', 'openclaw')

    def test_running_chat_terminal_does_not_start_or_replace_services(self):
        with patch.object(cli.chat, 'compose', return_value=subprocess.CompletedProcess([],0,'container-id\n')) as compose:
            cli.chat.main('shell', 'hermes', shell_args=['-lc', 'id -u'])
        self.assertEqual(len(compose.call_args_list), 2)
        self.assertEqual(compose.call_args_list[0].args, ('ps', '--status', 'running', '-q', 'hermes'))
        self.assertEqual(compose.call_args_list[1].args[-4:], ('hermes', 'bash', '-lc', 'id -u'))

    def test_opencode_start_reuses_container_without_rewriting_config_or_attaching(self):
        existing = {'Config':{'Labels':{'oc-local.lifecycle':'persistent-v1'}},
                    'HostConfig':{'Privileged':False,'NetworkMode':'bridge'},
                    'Mounts':[], 'State':{'Running':True,'Status':'running'}}
        def run(argv, **kwargs):
            if argv == ['docker','info']:
                return subprocess.CompletedProcess(argv,0)
            if argv == ['docker','container','inspect','oc-local-isolated-default']:
                return subprocess.CompletedProcess(argv,0,json.dumps([existing]))
            self.fail('Unexpected mutation: '+repr(argv))
        with patch.object(cli.opencode.shutil,'which',return_value='/mock/docker'), patch.object(cli.opencode.subprocess,'run',side_effect=run), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.opencode.main(['up']),0)

    def test_pairing_passes_invite_on_stdin(self):
        with patch.object(cli.chat,'compose') as compose:
            cli.chat.main('pair','hermes',owner='owner',invite='private-invite')
        self.assertNotIn('private-invite',compose.call_args.args)
        self.assertEqual(json.loads(compose.call_args.kwargs['input']),{'owner':'owner','invite':'private-invite'})


if __name__ == '__main__':
    unittest.main()
