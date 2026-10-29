"""Read-only bounded process-group census. It never authorizes cleanup or publication."""
import os
import sys

FIELDS = ('members', 'zombies', 'live', 'unknown_state', 'same_uid', 'leader', 'parent_is_init')
STATUSES = {'OK', 'UNAVAILABLE', 'MALFORMED', 'NOT_SUPPORTED'}


def project(value):
    value = value if type(value) is dict else {}
    status = value.get('status')
    result = {'status': status if type(status) is str and status in STATUSES else 'UNAVAILABLE'}
    if value.get('observer_cleanup_failed') is True:
        result['observer_cleanup_failed'] = True
    if result['status'] == 'OK':
        for name in FIELDS:
            number = value.get(name)
            if type(number) is not int or not 0 <= number <= 20000:
                return {'status': 'MALFORMED'}
            result[name] = number
        if result['members'] != result['zombies']+result['live']+result['unknown_state'] or any(
                result[x] > result['members'] for x in ('same_uid', 'leader', 'parent_is_init')):
            return {'status': 'MALFORMED'}
    return result


def parse(raw, pgid, uid):
    if type(raw) is not str or len(raw) > 1024*1024:return {'status': 'MALFORMED'}
    result = dict.fromkeys(FIELDS, 0)
    seen = set()
    lines = raw.splitlines()
    if len(lines) > 20000:return {'status': 'MALFORMED'}
    for line in lines:
        columns = line.split()
        if len(columns) != 5:return {'status': 'MALFORMED'}
        pid, parent, group, state, owner = columns
        if not all(x.isascii() and x.isdigit() and len(x) <= 10 for x in (pid,parent,group,owner)):
            return {'status': 'MALFORMED'}
        pid,parent,group,owner = map(int,(pid,parent,group,owner))
        if pid in seen:return {'status': 'MALFORMED'}
        seen.add(pid)
        if group != pgid:continue
        if not state or len(state) > 8 or not state.isascii():return {'status': 'MALFORMED'}
        result['members'] += 1
        result['zombies' if state[0] == 'Z' else 'live' if state[0] in 'RSITUD' else 'unknown_state'] += 1
        result['same_uid'] += owner == uid
        result['leader'] += pid == pgid
        result['parent_is_init'] += parent == 1
    return {'status': 'OK', **result}


def capture(pgid):
    if sys.platform not in {'darwin','linux'}:return {'status': 'NOT_SUPPORTED'}
    # The nested runner has no observer, so it cannot recursively take snapshots.
    # ps has a fixed argv containing neither command lines nor environment values.
    from scripts.ci_process import run_bounded
    detail = {}
    try:
        result = run_bounded(['/bin/ps', '-axo', 'pid=,ppid=,pgid=,stat=,uid='],
            cwd='/', env={'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C'},
            seconds=2, maximum=1024*1024, check=True, diagnostic=detail)
        return parse(result.stdout, pgid, os.getuid())
    except (InterruptedError, KeyboardInterrupt, SystemExit):
        return {'status': 'UNAVAILABLE', 'observer_cancelled': True,
                **({'observer_cleanup_failed': True} if detail.get('cleanup_failed') is True else {})}
    except Exception:
        return {'status': 'UNAVAILABLE', **({'observer_cleanup_failed': True} if detail.get('cleanup_failed') is True else {})}
