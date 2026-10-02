"""Live Phase 2 acceptance on a blank disposable map; no UI automation."""
import argparse
import hashlib
import json
import time
from pathlib import Path

from dungeondraft_mcp.bridge_client import BridgeClient, BridgeError
from dungeondraft_mcp.server import cancel_batch, get_batch, save_map, _wait_for_file

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args()
out = args.output_dir.resolve()
out.mkdir(exist_ok=False)
b = BridgeClient()


def apply_batch(operations, idempotency_key, wait=True):
    from dungeondraft_mcp.server import apply_batch as submit
    return submit(operations, out.name+':'+idempotency_key, wait=wait)


checks = []
report = {'passed': False, 'checks': checks, 'console_review': 'required'}


def asset(category, search=''):
    return b.request('list_assets', category=category, search=search, limit=1)['assets'][0]


def cleanup(job):
    for row in reversed(job['results']):
        if 'id' in row['result']:
            b.request('delete_element', id=row['result']['id'])


def preview(name):
    p = out/name
    b.request('export_map', path=str(p), ppi=24)
    _wait_for_file(str(p))
    return hashlib.sha256(p.read_bytes()).hexdigest()


try:
    assert b.request('ping')['protocol'] == 21
    status = b.request('get_status')
    assert not any(status['counts'].values())
    width, height = status['map_size_woxels']
    tree = asset('Objects', 'Oak')
    def trees(n):
        return [{'cmd': 'place_object', 'asset': tree, 'x': 300+(i%20)*(width-600)/19,
                 'y': 300+(i//20)*(height-600)/max(1,(n-1)//20), 'scale': 0.5} for i in range(n)]
    invalid = apply_batch([trees(1)[0], {'cmd': 'place_object', 'asset': 'missing', 'x': -1, 'y': 500, 'scale': 0}], 'invalid')
    assert not invalid['accepted'] and {e['index'] for e in invalid['validation_errors']} == {1}
    assert not any(b.request('get_status')['counts'].values())
    checks.append({'check': 'whole-batch validation before edits', 'errors': invalid['validation_errors']})
    for n in (10, 50, 200):
        ops = trees(n)
        started = time.perf_counter()
        job = apply_batch(ops, f'benchmark-{n}')
        elapsed = time.perf_counter()-started
        assert job['status'] == 'completed' and len(job['results']) == n, job
        ids = [row['result']['id'] for row in job['results']]
        assert len(set(ids)) == n and b.request('get_status')['counts']['objects'] == n
        replay = apply_batch(ops, f'benchmark-{n}')
        assert replay['job_id'] == job['job_id'] and replay['results'] == job['results']
        assert b.request('get_status')['counts']['objects'] == n
        try:
            apply_batch(ops+[ops[0]], f'benchmark-{n}')
        except BridgeError:
            pass
        else:
            raise AssertionError('conflicting key accepted')
        checks.append({'check': 'object batch and idempotent replay', 'count': n, 'seconds': elapsed,
                       'max_frame_ms': job['max_frame_ms']})
        cleanup(job)
    save_map(str(out/'baseline.dungeondraft_map'))
    dirty_before = b.request('get_map_info')['bridge_dirty']
    job = apply_batch(trees(200), 'cancel-objects', wait=False)
    assert b.request('ping')['pong']
    progress = get_batch(job['job_id'], include_results=False)
    assert progress['status'] in ('queued', 'running'), progress
    try:
        b.request('place_object', asset=tree, x=1000, y=1000)
    except BridgeError as exc:
        assert 'batch is active' in str(exc)
    else:
        raise AssertionError('concurrent bridge mutation allowed')
    cancelled = cancel_batch(job['job_id'])
    assert cancelled['status'] == 'cancelled', cancelled
    assert all(row['status'] == 'rolled_back' for row in cancelled['results'])
    assert not any(b.request('get_status')['counts'].values())
    assert b.request('get_map_info')['bridge_dirty'] == dirty_before
    checks.append({'check': 'responsive ping, edit isolation, cancellation rollback', 'processed': cancelled['processed']})
    before_png = preview('before-cancel.png')
    grass = asset('Terrain', 'Grass')
    dirt = asset('Terrain', 'Dirt')
    mixed = [
        {'cmd': 'fill_terrain', 'slot': 0, 'asset': grass},
        {'cmd': 'paint_path', 'slot': 1, 'asset': dirt, 'points': [[width/2,100],[width/2+100,height/2],[width/2,height-100]], 'radius': 150},
        {'cmd': 'draw_wall', 'asset': asset('Walls'), 'points': [[1000,1000],[1800,1000],[1800,1800],[1000,1800]], 'loop': True},
        {'cmd': 'draw_path', 'asset': asset('Paths'), 'points': [[1200,2200],[2000,2300]]},
        {'cmd': 'add_light', 'x': 1500, 'y': 1500, 'energy': 1.2},
        {'cmd': 'add_portal', 'asset': asset('Portals'), 'x': 2100, 'y': 1200, 'mount': 'free'},
    ]
    job = apply_batch(mixed+trees(200), 'cancel-mixed', wait=False)
    assert job['accepted'], job
    deadline = time.monotonic()+90
    while True:
        progress = get_batch(job['job_id'], include_results=False)
        assert progress['status'] in ('queued', 'running'), progress
        if progress['processed'] >= len(mixed):
            break
        assert time.monotonic() < deadline, progress
        time.sleep(0.02)
    cancelled = cancel_batch(job['job_id'])
    assert cancelled['status'] == 'cancelled', cancelled
    assert not any(b.request('get_status')['counts'].values())
    after_png = preview('after-cancel.png')
    assert before_png == after_png, (before_png, after_png)
    assert b.request('get_map_info')['bridge_dirty'] == dirty_before
    checks.append({'check': 'mixed rollback restores textures and rendered terrain', 'processed': cancelled['processed'], 'sha256': after_png})
    planned = []
    for i in range(50):
        side = -1 if i%2==0 else 1
        planned.append({'cmd':'place_object','asset':tree,'x':width/2+side*(600+((i//2)%5)*420),
                        'y':300+(i//10)*(height-600)/4+(i%10)*15,'scale':0.6,'rotation':i*17})
    sample = apply_batch(mixed[:2]+planned+mixed[2:], 'sample')
    assert sample['status'] == 'completed', sample
    assert b.request('get_status')['counts']['objects'] == 50
    report['sample_save'] = save_map(str(out/'sample.dungeondraft_map'))
    report['sample_preview_sha256'] = preview('sample.png')
    report['sample_job'] = sample
    cleanup(sample)
    assert not any(b.request('get_status')['counts'].values())
    report['cleaned_save'] = save_map(str(out/'cleaned.dungeondraft_map'))
    report['passed'] = True
finally:
    (out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key:value for key,value in report.items() if key!='sample_job'},indent=2))
