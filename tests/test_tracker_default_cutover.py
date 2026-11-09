"""Schema 5 changes new defaults without overriding owners' stored modes."""
import json

import pytest

from lampastream.api import CouplingCreateBody
from lampastream.beat_trigger import EnergyTrigger
from lampastream.migration import migrate_file
from lampastream.models import Coupling, EnergyProfile, Profile
from lampastream.schema import empty_config, validate_current
from lampastream.storage import Storage


@pytest.mark.parametrize('version',[3,4])
@pytest.mark.parametrize('mode',['off','onset','tracker'])
def test_migration_preserves_every_stored_mode_and_retires_gain_floor(tmp_path,version,mode):
    data=empty_config()
    data['schema_version']=version
    data['couplings']=[Coupling(id='owner',beat_accent_mode=mode).to_dict()]
    row=EnergyProfile(id='energy').to_dict()
    row['tracker_gain_floor' if version==4 else 'onset_gain_floor']=.73
    if version==3:
        for field in ('onset_relative_k','onset_reference_window_s',
                      'onset_refractory_ms','onset_full_k'):
            row.pop(field)
    data['energy_profiles']=[row]
    original=json.dumps(data).encode()
    path=tmp_path/'config.json'
    path.write_bytes(original)
    assert migrate_file(path,check=True) and path.read_bytes()==original
    assert migrate_file(path)
    result=json.loads(path.read_bytes())
    assert result['schema_version']==5
    assert result['couplings']==data['couplings']
    assert not {'onset_gain_floor','tracker_gain_floor'} & result['energy_profiles'][0].keys()
    assert list(tmp_path.glob('*.pre-v5.*.bak'))[0].read_bytes()==original
    assert not migrate_file(path)
    assert Storage(path).get_coupling('owner').beat_accent_mode==mode


def test_new_couplings_default_to_tracker_in_model_and_api():
    assert Coupling().beat_accent_mode=='tracker'
    for profile in (EnergyProfile(),Profile()):
        assert (profile.onset_relative_k,profile.onset_reference_window_s,
                profile.onset_refractory_ms,profile.onset_full_k)==(8.,3.,160.,9.)
    body=CouplingCreateBody(name='New',player_id='p',analyser_id='a',zone_id='z',
                           energy_profile_id='e')
    assert body.beat_accent_mode=='tracker'
    assert body.model_copy(update={'beat_accent_mode':'onset'}).beat_accent_mode=='onset'


def test_current_schema_does_not_fall_back_or_accept_retired_gain_fields():
    data=empty_config()
    data['couplings']=[Coupling(id='c').to_dict()]
    data['couplings'][0].pop('beat_accent_mode')
    with pytest.raises(ValueError):
        validate_current(data)
    data['couplings'][0]['beat_accent_mode']='tracker'
    row=EnergyProfile(id='e').to_dict()
    data['energy_profiles']=[row]
    for field in ('onset_gain_floor','tracker_gain_floor'):
        row[field]=0.
        with pytest.raises((TypeError,ValueError)):
            validate_current(data)
        row.pop(field)


def test_tracker_uses_base_floor_without_any_gain_tied_addition():
    trigger=EnergyTrigger()
    # At 64x this logarithmic energy is above the original .08 base floor,
    # below the removed .08+.3 floor; the normal ratio/rise gates still apply.
    assert trigger.process(.005,0.,'bass') is not None
    assert trigger.gain==64.
    assert trigger.floor==.08
    assert not hasattr(trigger,'gain_floor')
    assert EnergyTrigger().process(.0005,0.,'bass') is None
