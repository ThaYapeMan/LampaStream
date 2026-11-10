"""Read-only checks for the Hue client lock in source and installed wheels."""
import re
from importlib import metadata


def verify_hue_dependency(requirements) -> None:
    declared = [item.replace(' ', '').lower().replace('_', '-') for item in requirements
                if item.lower().replace('_', '-').startswith('hue-entertainment')]
    pin = (re.fullmatch(r'hue-entertainment==([0-9][a-z0-9.+!-]*)', declared[0])
           if len(declared) == 1 else None)
    assert pin is not None, f'Hue Entertainment dependency must be pinned exactly; got {declared}'
    expected = pin[1]
    installed = metadata.version('hue-entertainment')
    assert installed == expected, (
        f'Hue Entertainment client requires {expected}; installed {installed}')
    print(f'Hue Entertainment client: hue-entertainment {installed}: PASS')
