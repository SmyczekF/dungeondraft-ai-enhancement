"""Live save/undo/redo checkpoint regression on a blank disposable map."""
import argparse
import json
from pathlib import Path

from dungeondraft_mcp.bridge_client import BridgeClient, BridgeError
from dungeondraft_mcp.server import save_map, _wait_for_native_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir', type=Path, required=True)
options = parser.parse_args()
out = options.output_dir.resolve()
out.mkdir(exist_ok=False)
b = BridgeClient()
checks = []


def dirty(expected, label):
    actual = b.request('get_map_info')['bridge_dirty']
    assert actual is expected, (label, actual, expected)
    checks.append({'check': label, 'bridge_dirty': actual})


report = {'passed': False, 'checks': checks}
try:
    assert b.request('ping')['protocol'] == 21
    assert not any(b.request('get_status')['counts'].values())
    tree = b.request('list_assets', category='Objects', search='Tree', limit=1)['assets'][0]
    initial = b.request('get_map_info')['bridge_instance']
    dirty(False, 'blank state')
    first = b.request('place_object', asset=tree, x=1500, y=1500)['id']
    dirty(True, 'unsaved create')
    save_map(str(out/'one-tree.dungeondraft_map'))
    dirty(False, 'verified save')
    b.request('undo'); dirty(True, 'undo away from save')
    b.request('redo'); dirty(False, 'redo to saved state')
    b.request('place_object', asset=tree, x=2300, y=1500)
    dirty(True, 'new edit after save')
    b.request('undo'); dirty(False, 'undo new edit to checkpoint')
    b.request('delete_element', id=first)
    dirty(True, 'irreversible deletion')
    b.request('redo'); dirty(True, 'redo cannot erase deletion dirtiness')
    b.request('undo'); dirty(True, 'undo cannot erase deletion dirtiness')
    late = out/'late-edit.dungeondraft_map'
    pending = b.request('save_map', path=str(late), overwrite=False)
    made = b.request('place_object', asset=tree, x=2000, y=2000)['id']
    _wait_for_native_json(late, None)
    b.request('confirm_save', save_token=pending['save_token'])
    dirty(True, 'edit after save request stays dirty')
    try:
        b.request('confirm_save', save_token=pending['save_token'])
    except BridgeError:
        checks.append({'check': 'stale confirmation rejected'})
    else:
        raise AssertionError('stale confirmation accepted')
    b.request('delete_element', id=made)
    report['save'] = save_map(str(out/'cleaned.dungeondraft_map'))
    dirty(False, 'cleaned verified checkpoint')
    assert not any(b.request('get_status')['counts'].values())
    assert b.request('ping')['bridge_instance'] == initial
    report['passed'] = True
finally:
    (out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
