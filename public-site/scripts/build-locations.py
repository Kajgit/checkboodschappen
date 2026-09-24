"""Maintainer-only, bounded OSM snapshot build; never called by visitor requests.

Raw source stays in ignored output/. The derived location database is ODbL 1.0,
not MIT; its metadata travels with it. Use --fetch for one manual snapshot query,
otherwise rebuild from an existing local input. No automatic retry or scheduling.
"""
import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUERY = '[out:json][timeout:90][maxsize:67108864];area["ISO3166-1"="NL"]["admin_level"="2"]->.nl;nwr["shop"="supermarket"](area.nl);out center tags;'
BRANDS = [('albert heijn', 'Albert Heijn'), ('ah', 'Albert Heijn'), ('jumbo', 'Jumbo'), ('plus', 'PLUS'),
          ('aldi', 'ALDI'), ('lidl', 'Lidl'), ('dirk', 'Dirk'), ('ekoplaza', 'Ekoplaza'),
          ('hoogvliet', 'Hoogvliet'), ('dekamarkt', 'DekaMarkt'), ('vomar', 'Vomar'), ('spar', 'SPAR'), ('coop', 'Coop'), ('poiesz', 'Poiesz')]

def normalize(data):
    if data.get('remark') or not isinstance(data.get('elements'), list):
        raise ValueError('Incomplete or invalid Overpass response; existing snapshot retained')
    stores, unknown = [], 0
    for element in data['elements']:
        tags = element.get('tags', {})
        if tags.get('shop') != 'supermarket' or tags.get('disused') == 'yes' or tags.get('access') == 'private':
            continue
        names = [tags.get('brand', ''), tags.get('name', ''), tags.get('operator', '')]
        if any('to go' in name.lower() for name in names):
            continue
        retailer = next((canonical for alias, canonical in BRANDS for name in names
                         if re.match(r'^' + re.escape(alias) + r'(?:\b|$)', name, re.I)), None)
        if not retailer:
            unknown += 1
            continue
        coords = element.get('center', element)
        lat, lon = coords.get('lat'), coords.get('lon')
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (lat, lon)) or not (50.5 <= lat <= 53.8 and 3 <= lon <= 7.3):
            continue
        identifier = f"{element['type']}/{element['id']}"
        stores.append({'id': identifier, 'retailer': retailer, 'name': tags.get('name') or retailer,
                       'lat': lat, 'lon': lon,
                       'address': ' '.join(filter(None, [tags.get('addr:street'), tags.get('addr:housenumber'), tags.get('addr:city')])),
                       'url': f'https://www.openstreetmap.org/{identifier}'})
    return {'version': 1, 'generatedAt': datetime.now(timezone.utc).isoformat(),
            'sourceDate': data.get('osm3s', {}).get('timestamp_osm_base'),
            'source': 'OpenStreetMap contributors', 'sourceUrl': 'https://www.openstreetmap.org/copyright',
            'license': 'ODbL-1.0', 'licenseUrl': 'https://opendatacommons.org/licenses/odbl/1-0/',
            'query': QUERY, 'coverage': 'Mapped supermarket records for supported chains in the Netherlands; not guaranteed complete or open.',
            'unmatchedRecords': unknown, 'stores': stores}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--input', type=Path, default=ROOT/'output/diagnostics/osm-supermarkets-nl.json')
    args = parser.parse_args()
    if args.fetch:
        import httpx
        response = httpx.post('https://overpass-api.de/api/interpreter', data={'data': QUERY},
                              headers={'User-Agent': 'BoodschappenWijzer/0.1 (manual location snapshot)'}, timeout=120)
        response.raise_for_status()
        data = response.json()
    else:
        data = json.loads(args.input.read_text())
    result = normalize(data)
    if len(result['stores']) < 1000:
        raise ValueError('Suspiciously small national snapshot; refusing to replace location data')
    if args.fetch:
        args.input.parent.mkdir(parents=True, exist_ok=True)
        args.input.write_text(json.dumps(data, ensure_ascii=False))
    target = ROOT/'public-site/generated/stores.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')) + '\n')
    temporary.replace(target)
    print(json.dumps({'stores': len(result['stores']), 'unknown': result['unmatchedRecords'],
                      'bytes': target.stat().st_size, 'sourceDate': result['sourceDate']}))
