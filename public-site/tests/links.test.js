import test from 'node:test';
import assert from 'node:assert/strict';
import {safeProductUrl,shopMapUrl,shopDirectionsUrl} from '../src/links.js';
import {normalizeCatalogue} from '../src/checkjebon.js';
test('product links require a genuine HTTPS destination and missing source links stay missing',()=>{
 assert.equal(safeProductUrl('javascript:alert(1)'),null);
 assert.equal(safeProductUrl('https://user:pass@example.com'),null);
 const data=normalizeCatalogue([{n:'ah',u:'https://www.ah.nl/producten/product/',d:[{n:'A',p:2,l:'wi123/a'},{n:'B',p:2},{n:'C',p:2,l:'https://www.ah.nl/producten/product/wi321/c'}]}]);
 assert.equal(data.products[0].productUrl,'https://www.ah.nl/producten/product/wi123/a');
 assert.equal(data.products[1].productUrl,null);
 assert.equal(data.products[2].productUrl,'https://www.ah.nl/producten/product/wi321/c');
});
test('shop links reference the selected branch and omit the visitor origin',()=>{
 const store={id:'node/123',lat:52.37,lon:4.89};
 assert.equal(shopMapUrl(store),'https://www.openstreetmap.org/node/123');
 assert.equal(new URL(shopDirectionsUrl(store)).searchParams.get('destination'),'52.37,4.89');
 assert.equal(new URL(shopDirectionsUrl(store)).searchParams.has('origin'),false);
 assert.equal(shopMapUrl({id:'../bad'}),null);
});
