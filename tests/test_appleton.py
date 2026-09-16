import argparse
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('appleton', str(ROOT / 'appleton'))
spec = importlib.util.spec_from_loader(loader.name, loader)
runner = importlib.util.module_from_spec(spec)
loader.exec_module(runner)


def pe(path, machine):
    data = bytearray(128)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3C, 64)
    data[64:68] = b'PE\0\0'
    struct.pack_into('<H', data, 68, machine)
    path.write_bytes(data)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.exe = self.root / 'test game.exe'
        pe(self.exe, 0x8664)
        self.cfg = runner.settings(ROOT / 'appleton.cfg')
        self.cfg['prefix_root'] = str(self.root / 'prefixes')
        self.cfg['wine_x86_64'] = str(self.exe)
        self.args = argparse.Namespace(exe=str(self.exe), game_dir=str(self.root),
                                      graphics=None, prefix=None, exe_args=['--name', 'two words'])

    def test_architectures(self):
        for machine, expected in runner.MACHINES.items():
            pe(self.exe, machine)
            self.assertEqual(runner.pe_arch(self.exe), expected)
            plan = runner.build_plan(self.args, self.cfg)
            self.assertEqual(plan['command'][1], '-x86_64' if machine == 0x8664 else '-arm64')
        pe(self.exe, 0x14C)
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            runner.pe_arch(self.exe)

    def test_arguments_and_isolation(self):
        first = runner.build_plan(self.args, self.cfg)
        self.assertEqual(first['command'][-3:], [str(self.exe), '--name', 'two words'])
        self.assertEqual(first['command'][:3], ['/usr/bin/arch', '-x86_64', '/usr/bin/env'])
        other = self.root / 'other'
        other.mkdir()
        self.args.game_dir = str(other)
        self.assertNotEqual(first['prefix'], runner.build_plan(self.args, self.cfg)['prefix'])

    def test_dry_run_no_prefix(self):
        result = subprocess.run([str(ROOT / 'appleton'), '--dry-run', '--prefix',
                                 str(self.root / 'dry-prefix'), str(self.exe), str(self.root)],
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)['architecture'], 'x86_64')
        self.assertFalse((self.root / 'dry-prefix').exists())

    def test_execution_and_reuse(self):
        self.args.graphics = 'dxvk'
        self.cfg['dxvk_x64'] = str(self.root)
        self.cfg['moltenvk'] = str(self.root / 'libMoltenVK.dylib')
        Path(self.cfg['moltenvk']).touch()
        for name in ('dxgi', 'd3d11', 'd3d10core', 'd3d9'):
            pe(self.root / (name + '.dll'), 0x8664)
        plan = runner.build_plan(self.args, self.cfg)
        prefix = Path(plan['prefix'])
        calls = []

        def run(command, current_plan, phase):
            calls.append(command)
            self.assertEqual(current_plan['cwd'], str(self.root))
            if command == plan['initialize']:
                (prefix / 'system.reg').touch()
                return 0
            self.assertTrue((prefix / 'drive_c/windows/system32/d3d11.dll').is_file())
            return 7

        with patch.object(runner.platform, 'system', return_value='Darwin'), \
             patch.object(runner.platform, 'machine', return_value='arm64'), \
             patch.object(runner.os, 'access', return_value=True), \
             patch.object(runner, 'apfs_check'), \
             patch.object(runner, 'run_wine', side_effect=run):
            self.assertEqual(runner.execute(plan), 7)
            self.assertEqual(runner.execute(plan), 7)
            self.assertEqual(calls, [plan['initialize'], plan['command'], plan['command']])
            plan['backend'] = 'd3dmetal'
            with self.assertRaisesRegex(ValueError, 'runtime differs'):
                runner.execute(plan)

    def test_verbose_and_log(self):
        self.args.verbose = True
        with patch.dict(runner.os.environ, {}, clear=True):
            plan = runner.build_plan(self.args, self.cfg)
        self.assertIn('+seh', plan['environment']['WINEDEBUG'])
        command = [runner.sys.executable, '-c',
                   'import sys; print("stdout"); print("stderr", file=sys.stderr); sys.exit(9)']
        with patch.object(runner.sys, 'stdout'), patch.object(runner.sys, 'stderr'):
            self.assertEqual(runner.run_wine(command, plan, 'game'), 9)
        log = Path(plan['log_file']).read_text()
        self.assertIn('stdout', log)
        self.assertIn('stderr', log)
        with patch.dict(runner.os.environ, {'WINEDEBUG': '+relay'}):
            self.assertEqual(runner.build_plan(self.args, self.cfg)['environment']['WINEDEBUG'], '+relay')

    def test_profiles(self):
        profiles = self.root / 'profiles.json'
        common = ['--profiles-file', str(profiles)]
        def cli(*args):
            return subprocess.run([str(ROOT / 'appleton'), *args], capture_output=True, text=True)
        saved = cli('profile', *common, '--graphics', 'wine', 'save', 'my-game',
                    str(self.exe), str(self.root), '--name', 'two words')
        self.assertEqual(saved.returncode, 0, saved.stderr)
        result = cli('run', *common, '--dry-run', 'my-game', '--fullscreen')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['command'][-4:],
                         [str(self.exe), '--name', 'two words', '--fullscreen'])
        self.assertEqual(cli('profile', *common, 'remove', 'my-game').returncode, 0)
        self.assertIn('Unknown profile', cli('run', *common, 'my-game').stderr)

    def test_initialization_failure_retry(self):
        plan = runner.build_plan(self.args, self.cfg)
        with patch.object(runner.platform, 'system', return_value='Darwin'), \
             patch.object(runner.platform, 'machine', return_value='arm64'), \
             patch.object(runner.os, 'access', return_value=True), \
             patch.object(runner, 'apfs_check'), \
             patch.object(runner, 'run_wine', return_value=3):
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, 'initialization failed.*log:'):
                    runner.execute(plan)

    def test_apfs(self):
        for fs in ('apfs', 'hfs'):
            result = subprocess.CompletedProcess([], 0, stdout=runner.plistlib.dumps({'FilesystemType': fs}))
            df = subprocess.CompletedProcess([], 0, stdout='Filesystem Blocks Used Available Capacity Mounted\n/dev/disk3s5 1 1 0 100% /System/Volumes/Data\n')
            with patch.object(runner.subprocess, 'run', side_effect=[df, result]):
                if fs == 'apfs':
                    runner.apfs_check(self.root / 'new')
                else:
                    with self.assertRaisesRegex(ValueError, 'APFS'):
                        runner.apfs_check(self.root / 'new')


if __name__ == '__main__':
    unittest.main()
