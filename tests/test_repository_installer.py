"""Installer boundaries tested without pretending to run apt/systemd in mocks."""
import importlib.util
import json
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/install-lampastream.sh'


def test_help_and_unsupported_platform_are_read_only(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path))
    result = subprocess.run([str(SCRIPT), '--help'], env=env, capture_output=True, text=True)
    assert result.returncode == 0 and '--check' in result.stdout
    for requirement in ('existing LampaStream target installation', 'Debian 13 (trixie)',
                        'x86_64', 'systemd running', '/run/systemd/system',
                        'Does not install, migrate or modify the host', 'docs/testing.md'):
        assert requirement in result.stdout
    assert not list(tmp_path.iterdir())
    release = Path('/etc/os-release').read_text()
    if 'ID=debian' in release and 'VERSION_ID="13"' in release:
        pytest.skip('This failure test runs only on unsupported review hosts')
    before = subprocess.check_output(['git', 'diff', '--binary'], cwd=ROOT)
    result = subprocess.run([str(SCRIPT), '--check'], env=env, capture_output=True, text=True)
    assert result.returncode != 0 and 'Supported target: Debian 13' in result.stderr
    assert subprocess.check_output(['git', 'diff', '--binary'], cwd=ROOT) == before
    assert not list(tmp_path.iterdir())


def test_shell_syntax():
    # Windows-mounted checkouts can appear executable despite Git's stored mode.
    entry = subprocess.check_output(
        ['git', 'ls-files', '-s', 'scripts/install-lampastream.sh'], cwd=ROOT, text=True)
    assert entry.startswith('100755 '), 'Fresh clones must support the executable installer'
    subprocess.run(['bash', '-n', str(SCRIPT), str(ROOT / 'scripts/setup-airplay.sh'),
                    str(ROOT / 'scripts/build-squeezelite.sh')], check=True)


def test_dependency_and_phase_contract():
    text = SCRIPT.read_text()
    packages = (ROOT / "scripts/native-build-packages.txt").read_text()
    for package in ('libasound2-dev', 'libfftw3-dev', 'libflac-dev', 'libmad0-dev',
                    'libmpg123-dev', 'libvorbis-dev', 'libfaad-dev', 'libcap2-bin',
                    'python3-venv', 'pkg-config', 'polkitd', 'avahi-daemon', 'cava'):
        assert package in text + packages
    assert 'npm ci' in text
    assert 'sha256sum --check' in text
    assert 'git archive' not in text  # invocation includes explicit repo/safety options
    assert 'archive HEAD' in text
    assert text.index('-m lampastream.migration') < text.index('systemctl restart avahi-daemon')
    assert text.index('verify "$RELEASE/venv"') < text.index('systemctl restart avahi-daemon')
    assert 'pip install -e' not in text
    assert 'LAMPASTREAM_DEFER_START=1' in text


def test_check_branch_never_installs_or_migrates():
    text = SCRIPT.read_text()
    check = text.split('if [[ "$CHECK" == 1 ]]; then', 1)[1].split('\nfi', 1)[0]
    assert 'verify "$PREFIX/.venv"' in check
    assert 'exit 0' in check
    for forbidden in ('apt-get', 'mkdir', 'chown', 'systemctl restart', '-m lampastream.migration'):
        assert forbidden not in check
    verification = (ROOT / 'scripts/verify-install.py').read_text()
    assert 'check=True' in verification


def load_hook(monkeypatch):
    # Only the Hatch base class is substituted. Run real generation and cleanup;
    # native compilation gets separate compiler tests / target build evidence.
    module = types.ModuleType('hatchling.builders.hooks.plugin.interface')
    module.BuildHookInterface = object
    monkeypatch.setitem(sys.modules, module.__name__, module)
    spec = importlib.util.spec_from_file_location('installer_build_hook', ROOT / 'hatch_build.py')
    hook_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook_module)
    return hook_module.CustomBuildHook


def test_build_commit_generated_without_source_mutation(tmp_path, monkeypatch):
    hook_type = load_hook(monkeypatch)
    hook = hook_type()
    hook.root = str(tmp_path)
    tracked = tmp_path / 'src/lampastream/_commit.py'
    tracked.parent.mkdir(parents=True)
    tracked.write_text('COMMIT = "stale"\n')
    monkeypatch.setenv('LAMPASTREAM_BUILD_COMMIT', '123456789abcdef')
    monkeypatch.setattr(hook, '_build_cavacore', lambda: Path(
        hook._generated.name, '_libcavacore.so').write_bytes(b'test boundary'))
    data = {}
    hook.initialize('standard', data)
    generated = {dest: Path(src) for src, dest in data['force_include'].items()}
    assert generated['lampastream/_commit.py'].read_text() == 'COMMIT = "123456789abcdef"\n'
    assert generated['lampastream/cavacore/_libcavacore.so'].exists()
    assert tracked.read_text() == 'COMMIT = "stale"\n'
    assert data['pure_python'] is False and data['infer_tag'] is True
    hook.finalize('standard', data, '')
    assert not generated['lampastream/_commit.py'].exists()


def test_metadata_rejects_injected_non_revision(tmp_path, monkeypatch):
    hook = load_hook(monkeypatch)()
    hook.root = str(tmp_path)
    monkeypatch.setenv('LAMPASTREAM_BUILD_COMMIT', 'bad";code')
    with pytest.raises(ValueError, match='hexadecimal'):
        hook.initialize('standard', {})


def test_every_service_must_be_active():
    text = SCRIPT.read_text()
    function = text.split('verify_services() {', 1)[1].split('\n}', 1)[0]
    # Model systemctl's real any-active exit convention: a single failed unit
    # must be caught even though LampaStream and the other services are active.
    shell = '''fail() { echo "$*"; exit 1; }
systemctl() { [[ "$*" != *shairport-sync* ]]; }
verify_services() {'''+function+'\n}\nverify_services\n'
    result = subprocess.run(['bash', '-c', shell], capture_output=True, text=True)
    assert result.returncode == 1
    assert 'Service is not active: shairport-sync' in result.stdout


def test_airplay_first_install_replaces_upstream_sample_only(tmp_path):
    text = (ROOT / 'scripts/setup-airplay.sh').read_text()
    detect = text.split('CONFIG_EXISTED=0', 1)[1].split('\n\n', 1)[0]
    write = text.split('if [[ "$CONFIG_EXISTED" == 0 ]]; then', 1)[1].split('\nfi', 1)[0]
    config = tmp_path / 'receiver.conf'
    for existing in (False, True):
        if existing:
            config.write_text('operator config')
        shell = ('CONFIG_EXISTED=0'+detect+'\n'
                 f'if [[ ! -f "{config}" ]]; then echo upstream-sample > "{config}"; fi\n'
                 'if [[ "$CONFIG_EXISTED" == 0 ]]; then'+write+'\nfi\n')
        shell = shell.replace('/usr/local/etc/shairport-sync.conf', str(config))
        subprocess.run(['bash', '-c', shell], check=True)
        if existing:
            assert config.read_text() == 'operator config'
        else:
            assert 'output_backend = "pipe"' in config.read_text()
            assert 'output_rate = 44100' in config.read_text()


@pytest.mark.parametrize('debian,arch,booted,success,message', [
    (True, 'x86_64', True, True, ''),
    (True, 'x86_64', False, False, 'booted systemd target is required'),
    (True, 'aarch64', True, False, 'x86_64 only'),
    (False, 'x86_64', True, False, 'Debian 13 (trixie) only'),
])
def test_platform_gate_read_only(tmp_path, debian, arch, booted, success, message):
    # Execute the real probe body with only OS identity paths substituted.
    # This proves the gate; it does not simulate an installed target.
    release = tmp_path / 'os-release'
    release.write_text('ID=debian\nVERSION_ID=13\nVERSION_CODENAME=trixie\n' if debian
                       else 'ID=ubuntu\nVERSION_ID=26.04\n')
    systemd = tmp_path / 'systemd'
    if booted:
        systemd.mkdir()
    function = SCRIPT.read_text().split('platform() {', 1)[1].split('\n}', 1)[0]
    function = function.replace('/etc/os-release', str(release)).replace(
        '/run/systemd/system', str(systemd))
    before = sorted(p.name for p in tmp_path.iterdir())
    shell = ('set -Eeuo pipefail\nfail() { echo "$*" >&2; exit 1; }\n'
             f'uname() {{ echo {arch}; }}\nplatform() {{'+function+'\n}\nplatform\n')
    result = subprocess.run(['bash', '-c', shell], capture_output=True, text=True)
    assert (result.returncode == 0) == success
    assert message in result.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_node_bootstrap_pin_matches_ci_and_locked_jsdom_engine():
    installer = SCRIPT.read_text()
    pin = re.search(r'node-v(\d+\.\d+\.\d+)-linux-x64', installer).group(1)
    workflow = (ROOT / '.github/workflows/ci.yml').read_text()
    assert re.search(r'node-version: ([\d.]+)', workflow).group(1) == pin
    lock = json.loads((ROOT / 'web/package-lock.json').read_text())
    requirement = lock['packages']['node_modules/jsdom']['engines']['node']
    # Installer deliberately stays on the locked dependency's Node 22 caret
    # branch. A future major-branch change needs an explicit bootstrap review.
    minimum = re.search(r'\^22\.(\d+)\.(\d+)', requirement)
    assert minimum is not None
    version = tuple(map(int, pin.split('.')))
    assert version[0] == 22
    assert version >= (22, *map(int, minimum.groups()))
    for doc in ('development.md', 'testing.md', 'installation.md'):
        assert f'Node {pin}' in (ROOT / 'docs' / doc).read_text()


@pytest.mark.parametrize('definition,conflict', [
    ('{ path=/usr/bin/squeezelite ; argv[]=/usr/bin/squeezelite -o default ; }', True),
    ('DAEMON=/usr/bin/squeezelite\nNAME=receiver', True),
    ('DAEMON="/usr/bin/squeezelite"', True),
    ('{ path=/usr/local/bin/squeezelite ; }', False),
    ('{ path=/usr/local/bin/lampastream-squeezelite-fifo ; }', False),
    ('/opt/lampastream/.venv/bin/lampastream', False),
])
def test_conflicting_squeezelite_definition(definition, conflict):
    body = SCRIPT.read_text().split('squeezelite_conflict_definition() {', 1)[1].split('\n}', 1)[0]
    result = subprocess.run(['bash', '-c', 'squeezelite_conflict_definition() {' + body +
                             '\n}\nsqueezelite_conflict_definition "$1"', '-', definition])
    assert (result.returncode == 0) == conflict


@pytest.mark.parametrize('mode,stuck', [('install', False), ('install', True), ('check', False)])
def test_conflicting_squeezelite_service_lifecycle(tmp_path, mode, stuck):
    text = SCRIPT.read_text()
    start = text.index('squeezelite_conflict_definition() {')
    functions = text[start:text.index('verify_services() {')]
    init = tmp_path / 'init.d'
    init.mkdir()
    (init / 'room-receiver').write_text('DAEMON=/usr/bin/squeezelite\n')
    (init / 'room-receiver').chmod(0o755)
    functions = functions.replace('/etc/init.d', str(init)).replace(
        '/proc/[0-9]*/exe', str(tmp_path / 'proc/[0-9]*/exe'))
    calls = tmp_path / 'calls'
    stopped = tmp_path / 'stopped'
    shell = f'''set -Eeuo pipefail
log() {{ echo "$*"; }}
fail() {{ echo "$*"; exit 1; }}
systemctl() {{
 echo "$*" >> '{calls}'
 case "$1" in
 list-unit-files) printf 'autovt@.service alias\ngetty@.service enabled\n'
 printf 'squeezelite.service enabled\nlampastream-fifo.service enabled\n' ;;
 list-units) printf 'room-receiver.service loaded active running receiver\n'
 echo 'getty@tty1.service loaded active running Getty' ;;
 show)
  case "$2" in
   *@.service) echo 'Bare template is not queryable' >&2; return 1 ;;
   getty@tty1.service) echo '/sbin/agetty'; return 0 ;;
  esac
  case "$3" in
   --property=ExecStart)
    case "$2" in
     squeezelite.service) echo '/usr/local/bin/squeezelite' ;;
     lampastream-fifo.service) echo '/usr/local/bin/lampastream-squeezelite-fifo' ;;
     *) echo '{init}/room-receiver start' ;;
    esac ;;
   --property=SourcePath) [[ "$2" != room-receiver.service ]] || echo '{init}/room-receiver' ;;
   --property=ActiveState) if [[ -f '{stopped}' ]]; then echo inactive; else echo active; fi ;;
  esac ;;
 stop) {'true' if stuck else f"touch '{stopped}'"} ;;
 esac
 return 0
}}
''' + functions + f'\nsqueezelite_conflicts {mode}\n'
    result = subprocess.run(['bash', '-c', shell], capture_output=True, text=True)
    assert 'room-receiver.service (active)' in result.stdout
    commands = calls.read_text().splitlines()
    assert not any('@.service' in c for c in commands)
    assert 'show getty@tty1.service --property=ExecStart --value' in commands
    assert 'stop squeezelite.service' not in commands
    assert 'stop lampastream-fifo.service' not in commands
    if mode == 'install':
        assert commands.index('disable room-receiver.service') < commands.index(
            'stop room-receiver.service')
        assert (result.returncode != 0) == stuck
        assert ('did not stop' if stuck else 'disabled and stopped') in result.stdout
    else:
        assert not any(c.startswith(('stop ', 'disable ')) for c in commands)
        assert not stopped.exists()


def test_airplay_metadata_build_fifo_and_service_arguments(tmp_path):
    text = (ROOT / 'scripts/setup-airplay.sh').read_text()
    # Execute the production configure argument block using a local capture executable.
    start = text.index('./configure \\\n')
    configure = text[start:text.index('\n\nmake -j', start)]
    (tmp_path / 'configure').write_text('#!/bin/sh\nprintf "%s\\n" "$@" > arguments\n')
    (tmp_path / 'configure').chmod(0o755)
    subprocess.run(['bash', '-c', configure], cwd=tmp_path, check=True)
    assert '--with-metadata' in (tmp_path / 'arguments').read_text().splitlines()
    # Execute the actual tmpfiles declaration with only its destination redirected.
    declaration = text[text.index("printf 'd /run/lampastream"):text.index('\nsystemd-tmpfiles')]
    destination = tmp_path / 'tmpfiles.conf'
    subprocess.run(['bash', '-c', declaration.replace('/etc/tmpfiles.d/lampastream-run.conf',
                                                     str(destination))], check=True)
    assert 'p /run/lampastream/airplay.metadata 0600 lampastream lampastream -' in destination.read_text()
    assert '--metadata-enable --metadata-pipename=/run/lampastream/airplay.metadata' in text


@pytest.mark.parametrize('name,expected', [
    ('receiver.sh', 'receiver.service'),
    ('receiver room', r'receiver\x20room.service'),
    ('receiver@', None),  # mangles to a bare template, also excluded
])
def test_sysv_conflict_names_are_queryable(tmp_path, name, expected):
    text = SCRIPT.read_text()
    start = text.index('squeezelite_conflict_definition() {')
    functions = text[start:text.index('verify_services() {')]
    init = tmp_path / 'init.d'
    init.mkdir()
    script = init / name
    script.write_text('DAEMON=/usr/bin/squeezelite\n')
    script.chmod(0o755)
    (init / 'not-executable').write_text('DAEMON=/usr/bin/squeezelite\n')
    functions = functions.replace('/etc/init.d', str(init)).replace(
        '/proc/[0-9]*/exe', str(tmp_path / 'proc/[0-9]*/exe'))
    calls = tmp_path / 'calls'
    shell = f'''set -Eeuo pipefail
log() {{ echo "$*"; }}
fail() {{ echo "$*"; exit 1; }}
systemctl() {{
 printf '%s\\n' "$*" >> '{calls}'
 case "$1" in
 list-unit-files|list-units) return 0 ;;
 show)
  case "$2" in *@.service|not-executable.service) return 99 ;; esac
  case "$3" in
   --property=ExecStart) echo /usr/bin/squeezelite ;;
   --property=ActiveState) echo inactive ;;
  esac ;;
 *) return 98 ;; # check must never mutate the host
 esac
 return 0
}}
''' + functions + '\nsqueezelite_conflicts check\n'
    result = subprocess.run(['bash', '-c', shell], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    queries = [line for line in calls.read_text().splitlines() if line.startswith('show ')]
    if expected is None:
        assert queries == []
    else:
        assert queries == [f'show {expected} --property={prop} --value'
                           for prop in ('ExecStart', 'SourcePath', 'ActiveState')]


def test_non_template_inspection_failure_remains_fatal(tmp_path):
    text = SCRIPT.read_text()
    start = text.index('squeezelite_conflict_definition() {')
    functions = text[start:text.index('verify_services() {')].replace(
        '/etc/init.d', str(tmp_path / 'empty-init'))
    shell = '''set -Eeuo pipefail
log() { echo "$*"; }
fail() { echo "$*"; exit 1; }
systemctl() {
 case "$1" in
 list-unit-files) echo 'real.service enabled' ;;
 list-units) return 0 ;;
 show) echo 'Real inspection failure' >&2; return 42 ;;
 esac
}
''' + functions + '\nsqueezelite_conflicts check\n'
    result = subprocess.run(['bash', '-c', shell], capture_output=True, text=True)
    assert result.returncode == 42
    assert 'Real inspection failure' in result.stderr


def _migration_functions(script_text: str) -> str:
    """Extract the three layout functions from the installer."""
    start = script_text.index('detect_layout() {')
    end = script_text.index('\ncase "${1:-}" in')
    return script_text[start:end]


def test_migrate_huesync_layout_moves_config(tmp_path):
    """migrate_huesync_layout copies the old config and logs the move."""
    text = SCRIPT.read_text()
    functions = _migration_functions(text)
    etc_huesync = tmp_path / 'etc' / 'huesync'
    etc_huesync.mkdir(parents=True)
    old_config = etc_huesync / 'config.json'
    old_config.write_text('{"schema_version": 1}')
    etc_lp = tmp_path / 'etc' / 'lampastream'
    new_config = etc_lp / 'config.json'
    shell = f'''set -Eeuo pipefail
log() {{ echo "$*"; }}
fail() {{ echo "$*"; exit 1; }}
id() {{ return 0; }}
install() {{
    local d=""
    while [[ "$1" == -* ]]; do shift 4 || shift; done
    mkdir -p "$1"
}}
cp() {{ command cp "$@"; }}
chown() {{ true; }}
chmod() {{ true; }}
systemctl() {{ return 1; }}
HUESYNC_CONFIG="{old_config}"
CONFIG="{new_config}"
HUESYNC_SERVICE="{tmp_path}/etc/systemd/system/huesync.service"
HUESYNC_RULES="{tmp_path}/etc/polkit-1/rules.d/49-huesync-airplay.rules"
{functions}
migrate_huesync_layout
'''
    result = subprocess.run(['bash', '-c', shell], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert new_config.exists()
    assert new_config.read_text() == '{"schema_version": 1}'
    assert 'Config moved' in result.stdout


def test_migrate_huesync_layout_idempotent(tmp_path):
    """Running migrate_huesync_layout twice does not overwrite an existing new config."""
    text = SCRIPT.read_text()
    functions = _migration_functions(text)
    etc_huesync = tmp_path / 'etc' / 'huesync'
    etc_huesync.mkdir(parents=True)
    old_config = etc_huesync / 'config.json'
    old_config.write_text('{"old": true}')
    etc_lp = tmp_path / 'etc' / 'lampastream'
    etc_lp.mkdir(parents=True)
    new_config = etc_lp / 'config.json'
    new_config.write_text('{"new": true}')
    shell = f'''set -Eeuo pipefail
log() {{ echo "$*"; }}
fail() {{ echo "$*"; exit 1; }}
id() {{ return 0; }}
install() {{ true; }}
cp() {{ command cp "$@"; }}
chown() {{ true; }}
chmod() {{ true; }}
systemctl() {{ return 1; }}
HUESYNC_CONFIG="{old_config}"
CONFIG="{new_config}"
HUESYNC_SERVICE="{tmp_path}/etc/systemd/system/huesync.service"
HUESYNC_RULES="{tmp_path}/etc/polkit-1/rules.d/49-huesync-airplay.rules"
{functions}
migrate_huesync_layout
'''
    result = subprocess.run(['bash', '-c', shell], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert new_config.read_text() == '{"new": true}', "Existing new config must not be overwritten"
    assert 'retaining existing' in result.stdout


def test_migrate_huesync_no_old_layout_is_noop(tmp_path):
    """migrate_huesync_layout does nothing when no old layout is present."""
    text = SCRIPT.read_text()
    functions = _migration_functions(text)
    etc_lp = tmp_path / 'etc' / 'lampastream'
    new_config = etc_lp / 'config.json'
    shell = f'''set -Eeuo pipefail
log() {{ echo "$*"; }}
fail() {{ echo "$*"; exit 1; }}
systemctl() {{ return 1; }}
HUESYNC_CONFIG="{tmp_path}/etc/huesync/config.json"
CONFIG="{new_config}"
HUESYNC_SERVICE="{tmp_path}/etc/systemd/system/huesync.service"
HUESYNC_RULES="{tmp_path}/etc/polkit-1/rules.d/49-huesync-airplay.rules"
{functions}
migrate_huesync_layout
'''
    result = subprocess.run(['bash', '-c', shell], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not new_config.exists()
    assert 'migrating' not in result.stdout


def test_cleanup_huesync_layout_removes_old_artifacts(tmp_path):
    """cleanup_huesync_layout removes old unit, rules, config, user and group."""
    text = SCRIPT.read_text()
    functions = _migration_functions(text)
    etc_huesync = tmp_path / 'etc' / 'huesync'
    etc_huesync.mkdir(parents=True)
    old_config = etc_huesync / 'config.json'
    old_config.write_text('{}')
    old_service = tmp_path / 'etc' / 'systemd' / 'system' / 'huesync.service'
    old_service.parent.mkdir(parents=True)
    old_service.write_text('[Unit]\nDescription=HueSync\n')
    old_rules = tmp_path / 'etc' / 'polkit-1' / 'rules.d' / '49-huesync-airplay.rules'
    old_rules.parent.mkdir(parents=True)
    old_rules.write_text('polkit.addRule(function(){});')
    shell = f'''set -Eeuo pipefail
log() {{ echo "$*"; }}
fail() {{ echo "$*"; exit 1; }}
systemctl() {{ true; }}
id() {{ return 0; }}
userdel() {{ true; }}
getent() {{ return 0; }}
groupdel() {{ true; }}
HUESYNC_CONFIG="{old_config}"
CONFIG="{tmp_path}/etc/lampastream/config.json"
HUESYNC_SERVICE="{old_service}"
HUESYNC_RULES="{old_rules}"
{functions}
cleanup_huesync_layout
'''
    result = subprocess.run(['bash', '-c', shell], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not old_service.exists(), "Old service unit must be removed"
    assert not old_rules.exists(), "Old polkit rules must be removed"
    assert not old_config.exists(), "Old config must be removed"
    assert not etc_huesync.exists(), "Old /etc/huesync must be removed"
    assert '/opt/huesync' in result.stdout, "Manual cleanup notice must be printed"


def test_cleanup_huesync_removes_unit_before_user(tmp_path):
    """Removal order: old unit/rules removed before huesync user/group."""
    text = SCRIPT.read_text()
    functions = _migration_functions(text)
    old_service = tmp_path / 'huesync.service'
    old_service.write_text('[Unit]')
    calls = tmp_path / 'calls'
    shell = f'''set -Eeuo pipefail
log() {{ echo "$*"; }}
fail() {{ echo "$*"; exit 1; }}
systemctl() {{ echo "systemctl $*" >> "{calls}"; true; }}
id() {{ return 0; }}
userdel() {{ echo "userdel $*" >> "{calls}"; true; }}
getent() {{ return 0; }}
groupdel() {{ echo "groupdel $*" >> "{calls}"; true; }}
HUESYNC_CONFIG="{tmp_path}/missing-config"
CONFIG="{tmp_path}/new-config"
HUESYNC_SERVICE="{old_service}"
HUESYNC_RULES="{tmp_path}/missing-rules"
{functions}
cleanup_huesync_layout
'''
    result = subprocess.run(['bash', '-c', shell], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    call_lines = calls.read_text().splitlines()
    reload_idx = next(i for i, line in enumerate(call_lines) if 'daemon-reload' in line)
    userdel_idx = next(i for i, line in enumerate(call_lines) if line.startswith('userdel'))
    assert reload_idx < userdel_idx, "daemon-reload (after unit removal) must precede userdel"


def test_detect_layout_old(tmp_path):
    """detect_layout reports huesync when only old config is present."""
    text = SCRIPT.read_text()
    functions = _migration_functions(text)
    etc_huesync = tmp_path / 'etc' / 'huesync'
    etc_huesync.mkdir(parents=True)
    old_config = etc_huesync / 'config.json'
    old_config.write_text('{}')
    shell = f'''set -Eeuo pipefail
log() {{ echo "$*"; }}
HUESYNC_CONFIG="{old_config}"
CONFIG="{tmp_path}/new-config"
HUESYNC_SERVICE=""
HUESYNC_RULES=""
{functions}
detect_layout
'''
    result = subprocess.run(['bash', '-c', shell], capture_output=True, text=True)
    assert result.returncode == 0
    assert 'huesync' in result.stdout.lower()
    assert 'migration required' in result.stdout


def test_detect_layout_new(tmp_path):
    """detect_layout reports lampastream when only new config is present."""
    text = SCRIPT.read_text()
    functions = _migration_functions(text)
    new_config = tmp_path / 'config.json'
    new_config.write_text('{}')
    shell = f'''set -Eeuo pipefail
log() {{ echo "$*"; }}
HUESYNC_CONFIG="{tmp_path}/missing"
CONFIG="{new_config}"
HUESYNC_SERVICE=""
HUESYNC_RULES=""
{functions}
detect_layout
'''
    result = subprocess.run(['bash', '-c', shell], capture_output=True, text=True)
    assert result.returncode == 0
    assert 'lampastream' in result.stdout.lower()


def test_detect_layout_mixed(tmp_path):
    """detect_layout reports mixed when both old and new configs are present."""
    text = SCRIPT.read_text()
    functions = _migration_functions(text)
    etc_huesync = tmp_path / 'etc' / 'huesync'
    etc_huesync.mkdir(parents=True)
    old_config = etc_huesync / 'config.json'
    old_config.write_text('{}')
    new_config = tmp_path / 'new-config.json'
    new_config.write_text('{}')
    shell = f'''set -Eeuo pipefail
log() {{ echo "$*"; }}
HUESYNC_CONFIG="{old_config}"
CONFIG="{new_config}"
HUESYNC_SERVICE=""
HUESYNC_RULES=""
{functions}
detect_layout
'''
    result = subprocess.run(['bash', '-c', shell], capture_output=True, text=True)
    assert result.returncode == 0
    assert 'mixed' in result.stdout.lower()


def test_detect_layout_fresh(tmp_path):
    """detect_layout reports fresh install when neither layout is present."""
    text = SCRIPT.read_text()
    functions = _migration_functions(text)
    shell = f'''set -Eeuo pipefail
log() {{ echo "$*"; }}
HUESYNC_CONFIG="{tmp_path}/missing-old"
CONFIG="{tmp_path}/missing-new"
HUESYNC_SERVICE=""
HUESYNC_RULES=""
{functions}
detect_layout
'''
    result = subprocess.run(['bash', '-c', shell], capture_output=True, text=True)
    assert result.returncode == 0
    assert 'fresh' in result.stdout.lower()


def test_check_branch_calls_detect_layout():
    """The --check branch must call detect_layout before squeezelite_conflicts."""
    text = SCRIPT.read_text()
    check = text.split('if [[ "$CHECK" == 1 ]]; then', 1)[1].split('\nfi', 1)[0]
    assert 'detect_layout' in check
    assert text.index('detect_layout') < text.index('squeezelite_conflicts check')


def test_migrate_huesync_layout_updates_shairport_fifo_paths(tmp_path):
    """migrate_huesync_layout rewrites /run/huesync/ FIFO paths in shairport-sync.conf."""
    text = SCRIPT.read_text()
    functions = _migration_functions(text)
    etc_huesync = tmp_path / 'etc' / 'huesync'
    etc_huesync.mkdir(parents=True)
    old_config = etc_huesync / 'config.json'
    old_config.write_text('{}')
    shairport_conf = tmp_path / 'shairport-sync.conf'
    shairport_conf.write_text(
        'pipe = {\n'
        '  name = "/run/huesync/airplay.pcm";\n'
        '}\n'
        'metadata = {\n'
        '  pipename = "/run/huesync/airplay.metadata";\n'
        '}\n'
    )
    new_config = tmp_path / 'etc' / 'lampastream' / 'config.json'
    shell = f'''set -Eeuo pipefail
log() {{ echo "$*"; }}
fail() {{ echo "$*"; exit 1; }}
systemctl() {{ return 1; }}
id() {{ return 0; }}
install() {{ mkdir -p "${{@: -1}}"; }}
cp() {{ command cp "$@"; }}
chown() {{ true; }}
chmod() {{ true; }}
HUESYNC_CONFIG="{old_config}"
CONFIG="{new_config}"
HUESYNC_SERVICE="{tmp_path}/missing.service"
HUESYNC_RULES="{tmp_path}/missing.rules"
{functions.replace('/usr/local/etc/shairport-sync.conf', str(shairport_conf))}
migrate_huesync_layout
'''
    result = subprocess.run(['bash', '-c', shell], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    updated = shairport_conf.read_text()
    assert '/run/huesync/' not in updated
    assert '/run/lampastream/airplay.pcm' in updated
    assert '/run/lampastream/airplay.metadata' in updated
    assert 'Updated FIFO paths' in result.stdout


def test_migrate_huesync_layout_skips_shairport_if_already_migrated(tmp_path):
    """migrate_huesync_layout does not touch shairport-sync.conf if paths are already correct."""
    text = SCRIPT.read_text()
    functions = _migration_functions(text)
    etc_huesync = tmp_path / 'etc' / 'huesync'
    etc_huesync.mkdir(parents=True)
    old_config = etc_huesync / 'config.json'
    old_config.write_text('{}')
    shairport_conf = tmp_path / 'shairport-sync.conf'
    original = 'pipe = { name = "/run/lampastream/airplay.pcm"; }\n'
    shairport_conf.write_text(original)
    new_config = tmp_path / 'etc' / 'lampastream' / 'config.json'
    shell = f'''set -Eeuo pipefail
log() {{ echo "$*"; }}
fail() {{ echo "$*"; exit 1; }}
systemctl() {{ return 1; }}
id() {{ return 0; }}
install() {{ mkdir -p "${{@: -1}}"; }}
cp() {{ command cp "$@"; }}
chown() {{ true; }}
chmod() {{ true; }}
HUESYNC_CONFIG="{old_config}"
CONFIG="{new_config}"
HUESYNC_SERVICE="{tmp_path}/missing.service"
HUESYNC_RULES="{tmp_path}/missing.rules"
{functions.replace('/usr/local/etc/shairport-sync.conf', str(shairport_conf))}
migrate_huesync_layout
'''
    result = subprocess.run(['bash', '-c', shell], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert shairport_conf.read_text() == original, "Already-migrated shairport conf must not be rewritten"
    assert 'Updated FIFO paths' not in result.stdout
