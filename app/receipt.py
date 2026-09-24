"""Local, selectable-text PDF and lossless PNG receipts from the same layout."""
from io import BytesIO
from pathlib import Path
from datetime import datetime
import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(reportlab.__file__).parent / 'fonts'
for name, filename in [('Receipt', 'Vera.ttf'), ('ReceiptBold', 'VeraBd.ttf')]:
    pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / filename)))


def money(cents):
    return f'€ {cents / 100:.2f}'.replace('.', ',')


def receipt_blocks(scenario):
    blocks = []
    def add(text, size=10, bold=False, price=None, color='#243c33'):
        font = 'ReceiptBold' if bold else 'Receipt'
        width = 405 if price is not None else 495
        lines, line = [], ''
        for word in str(text).split():
            # Split even a single unusually long product word safely.
            for char in (' ' if line else '') + word:
                if pdfmetrics.stringWidth(line + char, font, size) > width:
                    lines.append(line); line = ''
                line += char
        if line: lines.append(line)
        blocks.append((lines or [''], size, font, price, color))
    add('BoodschappenWijzer', 20, True)
    add('Prijsvergelijking · ' + datetime.now().strftime('%d-%m-%Y %H:%M'), 9)
    add(' + '.join(scenario['stores']), 14, True)
    missing = scenario.get('missing', [])
    add(f"{len(scenario['offers'])} van {len(scenario['offers']) + len(missing)} regels gevonden", 10, True)
    if missing:
        add('ONVOLLEDIG - ontbrekende artikelen zijn niet in het subtotaal inbegrepen.', 10, True, color='#ad402e')
    for store in scenario['stores']:
        add(store, 13, True)
        for offer in scenario['offers']:
            if offer['retailer'] != store: continue
            add(offer['product_name'], 10, True, money(offer['total_cents']))
            details = f"{offer['packages_needed']} verpakking(en)"
            if offer.get('unit_price'): details += ' · inhoud per verpakking: ' + str(offer['unit_price'])
            if offer.get('source'): details += ' · ' + offer['source']
            add(details, 8)
            if offer.get('loyalty_required'): add('Klantenkaart vereist', 8)
            if offer.get('promotion') or offer.get('valid_until'):
                add((offer.get('promotion') or 'Actie') + (' · t/m ' + offer['valid_until'] if offer.get('valid_until') else ''), 8)
    add('Boodschappen', 11, price=money(scenario['product_cents']))
    add('Reis', 11, price=money(scenario['travel_cents']))
    add('Subtotaal' if missing else 'Totaal', 14, True, money(scenario['total_cents']))
    if missing:
        add('Nog te kopen - niet inbegrepen', 12, True, color='#ad402e')
        reasons = {d['name']: '; '.join(r['message'] for r in d.get('reasons', [])[:1]) for d in scenario.get('missing_details', [])}
        for name in missing:
            add(name + (': ' + reasons[name] if reasons.get(name) else ''), 9)
    add('Prijsindicatie, geen kassabon. Prijzen en actievoorwaarden kunnen in de winkel afwijken.', 8)
    return blocks


def export_receipt(scenario, format):
    blocks = receipt_blocks(scenario)
    output = BytesIO()
    if format == 'pdf':
        canvas = Canvas(output, pagesize=(595, 842))
        canvas.setTitle('BoodschappenWijzer - boodschappenbon')
        y, page = 800, 1
        def footer():
            canvas.setFont('Receipt', 8); canvas.setFillColor('#65756d')
            canvas.drawRightString(555, 24, f'Pagina {page}')
        for lines, size, font, price, color in blocks:
            height = len(lines) * (size + 4) + 8
            if y - height < 45:
                footer(); canvas.showPage(); page += 1; y = 800
            canvas.setFont(font, size); canvas.setFillColor(color)
            if price: canvas.drawRightString(555, y, price)
            for line in lines:
                canvas.drawString(40, y, line); y -= size + 4
            y -= 8
        footer(); canvas.save()
    elif format == 'png':
        height = int(80 + sum(len(lines) * (size + 4) + 8 for lines, size, *_ in blocks))
        if height > 15000: raise ValueError('Deze bon is te lang voor PNG. Gebruik PDF.')
        image = Image.new('RGB', (1190, height * 2), 'white')
        draw = ImageDraw.Draw(image); y = 40
        fonts = {}
        for lines, size, font, price, color in blocks:
            key = (size, font)
            if key not in fonts:
                fonts[key] = ImageFont.truetype(str(FONT_DIR / ('VeraBd.ttf' if font == 'ReceiptBold' else 'Vera.ttf')), size * 2)
            face = fonts[key]
            if price: draw.text((1110, y * 2), price, fill=color, font=face, anchor='rt')
            for line in lines:
                draw.text((80, y * 2), line, fill=color, font=face, anchor='lt'); y += size + 4
            y += 8
        image.save(output, format='PNG')
    else:
        raise ValueError('Kies PDF of PNG.')
    return output.getvalue()
