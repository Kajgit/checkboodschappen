"""Build a code-only browser matcher from the authoritative Python rules.

Only the pure prefix and explicitly named retailer helpers are included. No
provider class, HTTP client, database, user data or runtime cache is copied.
"""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'app/groceries.py').read_text()
tree = ast.parse(source)
cutoff = next(node.lineno for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'PriceProvider')
allowed_imports = {'__future__', 'dataclasses', 'itertools', 'typing', 'math', 'json', 're',
                   'unicodedata', 'datetime', 'collections', 'product_identity', 'product_text'}
selected = []
for node in tree.body:
    if node.lineno < cutoff:
        if isinstance(node, ast.Import) and any(alias.name not in allowed_imports for alias in node.names):
            continue
        if isinstance(node, ast.ImportFrom) and node.module not in allowed_imports:
            continue
        selected.append(node)
    elif isinstance(node, ast.FunctionDef) and node.name in {'_normal', 'canonical_retailer'}:
        selected.append(node)
    elif isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'RETAILER_NAMES' for target in node.targets):
        selected.append(node)
modules = {'__init__': '', 'groceries': ast.unparse(ast.Module(body=selected, type_ignores=[]))}
for name in ('product_text', 'product_identity', 'product_facts'):
    modules[name] = (ROOT / f'app/{name}.py').read_text()
modules['bridge'] = (ROOT / 'public-site/python/bridge.py').read_text()
dest = ROOT / 'public-site/generated/matcher-python.json'
dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_text(json.dumps(modules, ensure_ascii=False, sort_keys=True) + '\n')
print(f'Built {dest.relative_to(ROOT)} ({dest.stat().st_size:,} bytes of application code)')
