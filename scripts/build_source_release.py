"""Export explicitly inventoried source files into a new directory.

No network, deployment, credentials, installed dependencies or generated data.
"""
import argparse
import hashlib
import json
import posixpath
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def export(destination):
    mappings = json.loads((ROOT / 'scripts/source-release-files.json').read_text())
    prepared = []
    seen = set()
    for entry in mappings:
        source, target = Path(entry['source']), Path(entry['target'])
        for path in (source, target):
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Inventory paths must stay relative')
        if str(target) in seen:
            raise ValueError(f'Duplicate destination: {target}')
        seen.add(str(target))
        file = ROOT / source
        if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(ROOT):
            raise ValueError(f'Not a regular project source: {source}')
        data = file.read_bytes()
        if entry.get('relocate_markdown_links'):
            def relocate(match):
                link = match.group(1)
                if ':' in link or link.startswith(('#', '/')):
                    return match.group(0)
                path, separator, fragment = link.partition('#')
                resolved = posixpath.normpath(str(source.parent / path))
                relative = posixpath.relpath(resolved, str(target.parent))
                return '](' + relative + (separator + fragment if separator else '') + ')'
            data = re.sub(r'\]\(([^)]+)\)', relocate, data.decode()).encode()
        prepared.append((target, data))
    destination.mkdir(parents=True, exist_ok=False)
    manifest = []
    for target, data in prepared:
        file = destination / target
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
        manifest.append({'path': str(target), 'bytes': len(data),
                         'sha256': hashlib.sha256(data).hexdigest()})
    (destination / 'SOURCE-MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Prepared {len(manifest)} explicitly inventoried files in {destination}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New directory; never overwrites existing files')
    export(parser.parse_args().output)
