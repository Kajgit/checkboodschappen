import json
import time
from io import BytesIO
from PIL import Image
from pypdf import PdfReader
from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings


def test_partial_receipt_downloads_all_lines_in_both_formats(tmp_path):
    offers = [{'product_name': f'Product {i} crème fraîche', 'packages_needed': 2,
               'retailer': 'Winkel', 'total_cents': 250, 'unit_price': '200 g',
               'source': 'Testbron', 'loyalty_required': True} for i in range(44)]
    scenario = {'stores': ['Winkel'], 'offers': offers, 'missing': ['molokhia'],
                'product_cents': 11000, 'travel_cents': 100, 'total_cents': 11100, 'complete': False}
    (tmp_path / 'comparison-cache.json').write_text(json.dumps({'test': {'created_at': time.time(), 'result': {'diagnostics': [scenario]}}}))
    client = TestClient(create_app(Settings(tmp_path, True)))
    headers = {'X-Requested-With': 'BoodschappenWijzer'}
    pdf = client.post('/api/shopping/receipt/pdf', headers=headers, json={'stores': ['Winkel']})
    assert pdf.status_code == 200 and pdf.headers['content-type'] == 'application/pdf'
    reader = PdfReader(BytesIO(pdf.content))
    assert len(reader.pages) > 1
    text = '\n'.join(page.extract_text() for page in reader.pages)
    for word in ['Product 0', 'Product 43', 'crème fraîche', 'molokhia', 'Subtotaal', '111,00', 'Klantenkaart vereist']:
        assert word in text
    png = client.post('/api/shopping/receipt/png', headers=headers, json={'stores': ['Winkel']})
    assert png.status_code == 200 and png.headers['content-type'] == 'image/png'
    image = Image.open(BytesIO(png.content)); image.verify()
    assert image.width == 1190 and image.height > 2000
    assert 'attachment' in png.headers['content-disposition']
    assert client.post('/api/shopping/receipt/pdf', headers=headers, json={'stores': ['Unknown']}).status_code == 409
    assert client.post('/api/shopping/receipt/svg', headers=headers, json={'stores': ['Winkel']}).status_code == 400
