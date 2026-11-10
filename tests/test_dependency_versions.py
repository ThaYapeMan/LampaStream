"""Installed/source Hue declarations must agree with the reviewed exact pin."""
import tomllib
from pathlib import Path

import pytest

from lampastream.dependency_versions import verify_hue_dependency


@pytest.mark.parametrize('requirements', [[], ['hue-entertainment>=0.1.2'],
    ['hue-entertainment==0.3.*'], ['hue-entertainment'],
    ['hue-entertainment==0.3.0', 'hue-entertainment>=0.1.2']])
def test_verifier_refuses_missing_floating_or_conflicting_hue_pin(requirements):
    with pytest.raises(AssertionError, match='must be pinned'):
        verify_hue_dependency(requirements)


@pytest.mark.parametrize('installed', ['0.1.2', '0.3.1'])
def test_verifier_refuses_installed_version_drift(monkeypatch, installed):
    monkeypatch.setattr('lampastream.dependency_versions.metadata.version', lambda _: installed)
    with pytest.raises(AssertionError, match='installed '+installed):
        verify_hue_dependency(['hue-entertainment==0.3.0'])


def test_verifier_reports_actual_pinned_client(capsys):
    manifest = tomllib.loads((Path(__file__).parents[1]/'pyproject.toml').read_text())
    pin = next(r for r in manifest['project']['dependencies'] if r.startswith('hue-entertainment'))
    verify_hue_dependency([pin])
    expected = pin.split('==')[1]
    assert capsys.readouterr().out == (
        f'Hue Entertainment client: hue-entertainment {expected}: PASS\n')


def test_reviewed_bot_pin_can_advance_without_a_second_hardcoded_version(monkeypatch, capsys):
    monkeypatch.setattr('lampastream.dependency_versions.metadata.version', lambda _: '0.4.0')
    verify_hue_dependency(['hue-entertainment==0.4.0'])
    assert 'hue-entertainment 0.4.0: PASS' in capsys.readouterr().out


def test_installed_wheel_pin_must_match_its_actual_client(monkeypatch):
    monkeypatch.setattr('lampastream.dependency_versions.metadata.version', lambda _: '0.3.0')
    with pytest.raises(AssertionError, match='requires 0.1.2; installed 0.3.0'):
        verify_hue_dependency(['hue-entertainment==0.1.2'])
