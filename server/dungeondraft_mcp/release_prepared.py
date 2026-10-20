"""Package reviewed, hash-pinned artwork and a connected Foundry scene offline.

Preserves native v14 levels, regions and embedded overhead Tiles. Artwork may
combine native components (for example a flat guard deck or a canopy preview).
"""
import base64
import json
import os
from pathlib import Path
import re
import tempfile

from .editor_lifecycle import read_native
from .layout.vtt import NAMESPACE
from .release import ReleaseError, digest, inside, png_size, public_scene, read_json, write_zip


def build_prepared_release(config):
    root = Path(config).resolve().parent
    cfg = read_json(config)
    allowed = {'title', 'slug', 'native_map', 'pixels_per_square', 'export_metadata',
               'scene', 'artwork', 'readme', 'patreon_readme', 'actor'}
    required = allowed - {'actor'}
    if set(cfg) - allowed or not required <= set(cfg):
        raise ReleaseError('Invalid prepared release configuration')
    if not isinstance(cfg['title'], str) or not cfg['title'].strip():
        raise ReleaseError('Release title is required')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', cfg['slug']):
        raise ReleaseError('Invalid release slug')
    ppi = cfg['pixels_per_square']
    if type(ppi) is not int or not 50 <= ppi <= 256:
        raise ReleaseError('Invalid pixels_per_square')
    sources = {}

    def read(relative):
        data = inside(root, relative).read_bytes()
        sources[relative] = digest(data)
        return data

    native = read(cfg['native_map'])
    world = read_native(inside(root, cfg['native_map']))['world']
    size = (world['width'], world['height'])
    expected = tuple(v * ppi for v in size)
    if max(expected) > 8192 or expected[0] * expected[1] > 16_000_000:
        raise ReleaseError('Artwork exceeds native export limits')
    meta = json.loads(read(cfg['export_metadata']))
    scene_data = read(cfg['scene'])
    if meta.get('native_sha256') != digest(native):
        raise ReleaseError('Prepared native export is stale')
    if meta.get('scene_sha256') != digest(scene_data):
        raise ReleaseError('Scene hash does not match export metadata')
    scene, _ = public_scene(json.loads(scene_data), expected, ppi, connected=True)
    level_names = {q['name'] for q in scene['levels']}
    native_names = {q['label'] for q in world['levels'].values()}
    captured, names, covered = set(), set(), set()
    files = {k: {} for k in ('gridded', 'gridless', 'foundry')}
    artwork = cfg['artwork']
    if not isinstance(artwork, list) or not artwork:
        raise ReleaseError('Prepared artwork is required')
    for art in artwork:
        if set(art) != {'name', 'levels', 'native_labels', 'gridded', 'gridless',
                       'gridded_sha256', 'gridless_sha256'}:
            raise ReleaseError('Invalid prepared artwork entry')
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', art['name']) or art['name'] in names:
            raise ReleaseError('Artwork names must be unique filename-safe slugs')
        names.add(art['name'])
        if not art['levels'] or not set(art['levels']) <= level_names or covered.intersection(art['levels']):
            raise ReleaseError('Artwork must uniquely cover the playable scene levels')
        covered.update(art['levels'])
        captured.update(art['native_labels'])
        pair = {}
        for kind in ('gridded', 'gridless'):
            data = read(art[kind])
            if digest(data) != art[kind + '_sha256']:
                raise ReleaseError('Prepared artwork hash is stale: ' + art[kind])
            if png_size(data) != expected:
                raise ReleaseError('Prepared artwork dimensions differ from the native map')
            pair[kind] = data
            files[kind][f"{cfg['slug']}-{art['name']}.png"] = data
        if pair['gridded'] == pair['gridless']:
            raise ReleaseError('Gridded artwork must contain a visible grid')
    if captured != native_names or covered != level_names:
        raise ReleaseError('Artwork must cover all native components and playable scene levels')
    files['foundry'][cfg['slug'] + '-scene.json'] = json.dumps(scene, indent=2, ensure_ascii=False).encode('utf-8')
    if cfg.get('actor'):
        data = read(cfg['actor'])
        if digest(data) != meta.get('vehicle_sha256'):
            raise ReleaseError('Vehicle Actor hash is stale')
        actor = json.loads(data)
        if actor.get('type') != 'vehicle':
            raise ReleaseError('Expected the prepared Vehicle Actor')
        for src in [actor.get('img', ''), actor.get('prototypeToken', {}).get('texture', {}).get('src', '')]:
            if not src.startswith(('data:image/png;base64,', 'data:image/webp;base64,')):
                raise ReleaseError('Vehicle artwork must be self-contained')
            base64.b64decode(src.split(',', 1)[1], validate=True)
        actor.get('flags', {}).pop(NAMESPACE, None)
        files['foundry'][cfg['slug'] + '-vehicle.json'] = json.dumps(actor, indent=2, ensure_ascii=False).encode('utf-8')
    readme = read(cfg['readme'])
    patreon = read(cfg['patreon_readme'])
    for content in files.values():
        content['READ-ME.txt'] = readme
        content['PATREON-README.md'] = patreon
    counts = {k: len(scene.get(k, [])) for k in ('levels', 'tiles', 'walls', 'lights', 'regions')}
    counts.update(doors=sum(w.get('door') == 1 for w in scene.get('walls', [])),
                  secrets=sum(w.get('door') == 2 for w in scene.get('walls', [])))
    output = inside(root, 'release')
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.release-', dir=root) as temporary:
        stage = Path(temporary)
        artifacts = {}
        for kind, content in files.items():
            name = cfg['slug'] + '-' + kind + '.zip'
            write_zip(stage / name, content)
            artifacts[name] = digest((stage / name).read_bytes())
        # Refuse mixed revisions even if a background export changed mid-build.
        if any(digest(inside(root, p).read_bytes()) != h for p, h in sources.items()):
            raise ReleaseError('A prepared source changed during packaging')
        notes = (f"{cfg['title']} - {size[0]}x{size[1]}\n"
                 f"{len(artwork)} image floor(s), {len(scene['levels'])} connected Foundry level(s).\n"
                 f"5 feet per square; {ppi} pixels per square.\n\n"
                 + '\n'.join(artifacts) + '\n\n'
                 'See READ-ME.txt for import, lighting, movement and GM notes.\n'
                 'PATREON-README.md contains the English post title and description.\n'
                 'Files validated offline; live import/player vision require a world check.\n')
        (stage / 'RELEASE-NOTES.txt').write_text(notes, encoding='utf-8')
        manifest = {'title': cfg['title'], 'native_sha256': digest(native),
                    'source_sha256': sources, 'artifacts': artifacts, 'counts': counts,
                    'image_floors': len(artwork), 'connected_scene': True, 'runtime_verified': False}
        (stage / 'build.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        for kind in ('gridded', 'gridless'):
            folder = output / kind
            folder.mkdir(exist_ok=True)
            for name, data in files[kind].items():
                (stage / name).write_bytes(data)
                os.replace(stage / name, folder / name)
        for name in [*artifacts, 'RELEASE-NOTES.txt', 'build.json']:
            os.replace(stage / name, output / name)
        (output / 'READ-ME.txt').write_bytes(readme)
        (output / 'PATREON-README.md').write_bytes(patreon)
    print(f'Release ready: {output}', flush=True)
    return output
