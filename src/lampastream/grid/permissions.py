"""Installer-owned grid database permissions and service-user access verification."""
from __future__ import annotations

import argparse
import grp
import os
import pwd
import sqlite3
from pathlib import Path

from .database import GridDatabase


def owned_files(database):
    """Exact sidecars plus migration and restore safety backups in this directory."""
    database = Path(database)
    return tuple(dict.fromkeys((database, Path(str(database)+'.lock'),
                                Path(str(database)+'.restore-pending'),
                                *sorted(database.parent.glob('grids.pre-sqlite.*.tar')),
                                *sorted(database.parent.glob('.grid-safety-*')),
                                *sorted(database.parent.glob(database.name+'.pre-*')))))


def set_owner(database, uid, gid):
    database = Path(database)
    # A root-owned database must not cause root-run maintenance to leave its
    # stable lock inaccessible to the service on the next open.
    os.chown(database.parent, uid, gid, follow_symlinks=False)
    os.chmod(database.parent, 0o750)
    for path in owned_files(database):
        if not path.exists() and path != Path(str(database)+'.lock'):
            continue
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            os.fchown(descriptor, uid, gid)
            os.fchmod(descriptor, 0o600 if path.name.endswith('.lock') else 0o640)
        finally:
            os.close(descriptor)


def check_access(database):
    database = Path(database)
    if not Path(str(database)+'.lock').is_file():
        raise PermissionError('Grid lock missing; rerun the standard installer')
    with GridDatabase(database).connect() as connection:
        connection.execute('SELECT 1').fetchone()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('own', 'check'))
    parser.add_argument('database', type=Path)
    parser.add_argument('--user', default='lampastream')
    parser.add_argument('--group', default='lampastream')
    args = parser.parse_args()
    owner = pwd.getpwnam(args.user)
    if args.action == 'own':
        set_owner(args.database, owner.pw_uid, grp.getgrnam(args.group).gr_gid)
    else:
        if os.geteuid() != owner.pw_uid:
            parser.exit(1, 'Grid database access: FAIL '
                        '(run --check with sudo or as the service user)\n')
        try:
            check_access(args.database)
        except (OSError, ValueError, sqlite3.Error) as error:
            parser.exit(1, f'Grid database access: FAIL ({type(error).__name__})\n')
        print('Grid database access: PASS')


if __name__ == '__main__':
    main()
