const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const euro = cents => new Intl.NumberFormat('nl-NL', {style: 'currency', currency: 'EUR'}).format((cents || 0) / 100);
const productSearchCache = new Map();
let selectedProduct = null;
let selectedIntent = null;
let enteredQuery = '';
let productResults = [];
let shoppingItems = [];
let suggestions = [];
let searchTimer = null;
let searchController = null;
let receiptScenarios = new Map();
let receiptCounter = 0;

const BASIC_INTENTS = {
  'Halfvolle melk': {family: 'melk', attributes: ['halfvol', 'normaal'], exclusions: ['koffiemelk', 'yoghurt', 'proteïne', 'chocolade', 'houdbaar']},
  'Bruinbrood': {family: 'brood', attributes: ['bruin', 'heel of half brood'], exclusions: ['naan', 'stokbrood', 'broodje', 'snack']},
  'Jonge kaas 48+ stuk': {family: 'kaas', attributes: ['jong', '48+', 'stuk'], exclusions: ['plakken', 'rasp', 'blokjes', 'smeerkaas']},
  'Kipfilet': {family: 'kipfilet', attributes: ['onbereid', 'normaal'], exclusions: ['vleeswaren', 'snack', 'gepaneerd', 'gekruid']},
  'Witte bolletjes': {family: 'broodjes', attributes: ['wit', 'bolletjes'], exclusions: ['chocolade', 'kaas', 'snack', 'hamburger']},
};

async function api(path, options = {}) {
  const comparing = path === '/api/shopping/compare';
  if (comparing) {
    $('#compare').disabled = true;
    $('#compare').textContent = 'Bezig met vergelijken';
    $('#compare-status').hidden = false;
    $('#scenarios').innerHTML = '<div class="results-loading"><span class="spinner"></span><div><strong>Prijzen controleren</strong><p>Producten, verpakkingen en routes worden vergeleken.</p></div></div>';
  }
  options.headers = {...(options.headers || {}), 'X-Requested-With': 'BoodschappenWijzer'};
  if (options.body && !(options.body instanceof FormData)) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(options.body);
  }
  try {
    const response = await fetch(path, options);
    if (!response.ok) {
      let payload;
      try { payload = await response.json(); } catch { payload = {detail: 'Er ging iets mis.'}; }
      throw new Error(payload.detail || 'Er ging iets mis.');
    }
    return response;
  } finally {
    if (comparing) {
      $('#compare').disabled = false;
      $('#compare').textContent = 'Vergelijk mijn lijst';
      $('#compare-status').hidden = true;
    }
  }
}

function esc(value = '') {
  const node = document.createElement('div');
  node.textContent = value;
  return node.innerHTML.replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}
function safeUrl(value = '') {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? esc(url.href) : '#'; }
  catch { return '#'; }
}
function toast(message) {
  const node = $('#toast'); node.textContent = message; node.classList.add('show');
  setTimeout(() => node.classList.remove('show'), 2800);
}
function imageSrc(url) { return '/api/product-image?url=' + encodeURIComponent(url); }
function productIcon(name = '') {
  const value = name.toLowerCase();
  if (/melk|yoghurt|zuivel/.test(value)) return '🥛';
  if (/brood|bol|croissant/.test(value)) return '🥖';
  if (/kip|vlees|filet/.test(value)) return '🍗';
  if (/kaas/.test(value)) return '🧀';
  if (/groente|boon|sla|spinazie/.test(value)) return '🥬';
  return '🛒';
}
function image(url, className, name = '') {
  return url ? `<img class="${className}" src="${esc(imageSrc(url))}" alt="" loading="lazy">` :
    `<span class="${className} product-placeholder" aria-hidden="true">${productIcon(name)}</span>`;
}

$('#interpret-list').onclick = async () => {
  const text = $('#ai-list').value.trim();
  const people = +$('#ai-people').value;
  const useAI = $('#use-local-ai').checked;
  if (!text) return toast('Plak eerst een boodschappenlijst.');
  const button = $('#interpret-list'); button.disabled = true; button.textContent = 'Lijst wordt geïnterpreteerd…';
  const pending = $('#ai-suggestions'); pending.hidden = false;
  pending.innerHTML = `<p role="status">Producten en hoeveelheden controleren.${useAI ? ' Lokale AI kan bij een lange lijst enkele minuten duren.' : ''}</p>`;
  try {
    const result = await (await api('/api/shopping/interpret', {method: 'POST', body: {text, people, use_ai: useAI}})).json();
    suggestions = result.items || [];
    const box = $('#ai-suggestions'); box.hidden = false;
    const engine = result.engine === 'ollama' ? `Lokale AI (${result.model})` : result.engine === 'gemengd' ? 'AI en lokale regels' : 'Lokale regels, zonder AI';
    box.innerHTML = `<div class="ai-summary"><strong>${suggestions.length} boodschappenregels gevonden</strong><span>${esc(engine)}</span><span>${esc(result.notice || '')}</span><span>Hoeveelheden zonder opgegeven aantal zijn voorstellen, geen exacte receptberekening. Controleer ook dubbele regels.</span><span>Stuk = losse producten. Verpakking = een heel pak, zak of pot. Kg/liter = de totale benodigde inhoud.</span></div>` + suggestions.map((item, index) => `
      <div class="ai-suggestion" data-index="${index}"><input class="ai-include" type="checkbox" checked aria-label="${esc(item.name)} toevoegen">
      <label>Product<input class="ai-query" value="${esc(item.search_query)}"></label>
      <label>Hoeveelheid<input class="ai-qty" type="number" min="0.001" max="10000" step="any" value="${item.quantity}"></label>
      <label>Eenheid<select class="ai-unit"><option>stuk</option><option>verpakking</option><option>g</option><option>kg</option><option>ml</option><option>liter</option></select></label>
      <div class="ai-explanation"><strong>Invoer: ${esc(item.source_text || item.name)}</strong><span>${item.quantity_source === 'explicit' ? 'Hoeveelheid opgegeven' : 'Geschatte hoeveelheid'}${item.confidence === 'laag' ? ' · productkeuze controleren' : ''}</span><span>${esc(item.explanation || `Voor ${people} personen`)}</span>${item.ai_suggestion ? `<span>AI stelt een andere zoeknaam voor: ${esc(item.ai_suggestion)}. Alleen gebruiken als dit is wat je bedoelt; wijzig dan hierboven het product.</span>` : ''}${item.duplicate_count > 1 ? `<span>Komt ${item.duplicate_count} keer voor. Behouden als aparte regel; vink uit als dit een herhaling is.</span>` : ''}</div></div>`).join('') +
      '<button id="add-suggestions" class="primary">Toevoegen aan lijst</button>';
    $$('.ai-suggestion').forEach(row => row.querySelector('.ai-unit').value = suggestions[+row.dataset.index].unit);
    $('#add-suggestions').onclick = addSuggestions;
  } catch (error) { pending.innerHTML = ''; pending.hidden = true; toast(error.message); }
  finally { button.disabled = false; button.textContent = 'Controleren'; }
};

async function addSuggestions() {
  const rows = $$('.ai-suggestion').filter(row => row.querySelector('.ai-include').checked);
  if (!rows.length) return toast('Selecteer minimaal één product.');
  if (rows.some(row => !row.querySelector('.ai-qty').reportValidity() || row.querySelector('.ai-query').value.trim().length < 2)) {
    return toast('Vul per geselecteerde regel een product en een positieve hoeveelheid in.');
  }
  const button = $('#add-suggestions'); button.disabled = true;
  let added = 0;
  try {
    for (const row of rows) {
      const item = suggestions[+row.dataset.index];
      const query = row.querySelector('.ai-query').value.trim();
      const changed = query !== item.search_query;
      await api('/api/shopping-items', {method: 'POST', body: {
        query, display_name: query, quantity: +row.querySelector('.ai-qty').value,
        unit: row.querySelector('.ai-unit').value, allow_alternatives: true, match_mode: 'basis',
        product_family: changed ? null : item.family || 'overig', attributes: changed ? [] : item.attributes || [],
        exclusions: changed ? [] : item.exclusions || [], remember_quantity: false, review_confirmed: true,
      }});
      added++;
      row.querySelector('.ai-include').checked = false;
      row.querySelector('.ai-include').disabled = true;
      row.hidden = true;
    }
    $('#ai-suggestions').hidden = true; $('#ai-list').value = ''; suggestions = [];
    toast(`${added} producten toegevoegd`); await loadItems();
  } catch (error) {
    toast(`${added} toegevoegd. ${error.message} Je kunt de overige regels opnieuw proberen.`);
    await loadItems();
  } finally { button.disabled = false; }
}

$('#item-query').oninput = event => {
  selectedProduct = null; selectedIntent = null; enteredQuery = event.target.value.trim();
  $('#selected-product').hidden = true; $('#alternatives-label').hidden = true;
  clearTimeout(searchTimer);
  if (enteredQuery.length < 2) return void ($('#product-results').hidden = true);
  const query = enteredQuery;
  searchTimer = setTimeout(() => searchProducts(query), 350);
};

$$('[data-basic]').forEach(button => button.onclick = () => {
  selectedProduct = null; enteredQuery = button.dataset.basic;
  selectedIntent = {display_name: enteredQuery, ...BASIC_INTENTS[enteredQuery], match_mode: 'basis'};
  $('#item-query').value = enteredQuery; $('#item-unit').value = button.dataset.unit;
  $('#product-results').hidden = true; $('#alternatives-label').hidden = true;
  const box = $('#selected-product'); box.hidden = false;
  box.innerHTML = `<div><strong>${esc(enteredQuery)}</strong><div class="muted">${selectedIntent.attributes.map(esc).join(' | ')}</div></div>`;
});

async function searchProducts(query) {
  const box = $('#product-results'); const key = query.toLowerCase(); box.hidden = false;
  box.innerHTML = '<p class="loading-line"><span class="spinner"></span>Producten zoeken</p>';
  try {
    searchController?.abort(); searchController = new AbortController();
    productResults = productSearchCache.get(key) || await (await api('/api/products/search?q=' + encodeURIComponent(query), {signal: searchController.signal})).json();
    productSearchCache.set(key, productResults);
    if ($('#item-query').value.trim().toLowerCase() !== key) return;
    box.innerHTML = productResults.length ? productResults.map((product, index) => `
      <button type="button" class="product-option" data-index="${index}">${image(product.image_url, '', product.name)}
      <span><strong>${esc(product.name)}</strong><span>${esc(product.retailer)} | ${esc(product.quantity || 'verpakking')}</span></span>
      <strong>${euro(product.price_cents)}</strong></button>`).join('') : '<p class="muted">Geen producten gevonden.</p>';
    $$('.product-option').forEach(button => button.onclick = () => selectProduct(productResults[+button.dataset.index]));
  } catch (error) { if (error.name !== 'AbortError') box.innerHTML = `<p class="error">${esc(error.message)}</p>`; }
}

function selectProduct(product) {
  selectedProduct = product; selectedIntent = null; $('#item-query').value = product.name;
  $('#product-results').hidden = true; $('#alternatives-label').hidden = false; $('#allow-alternatives').checked = true;
  const box = $('#selected-product'); box.hidden = false;
  box.innerHTML = `${image(product.image_url, '', product.name)}<div><strong>${esc(product.name)}</strong><div class="muted">${esc(product.retailer)} | vergelijkbare producten toegestaan</div></div><strong>${euro(product.price_cents)}</strong>`;
}

$('#item-form').onsubmit = async event => {
  event.preventDefault();
  clearTimeout(searchTimer);
  searchController?.abort();
  const product = selectedProduct; const intent = selectedIntent || {};
  const query = enteredQuery || product?.name || $('#item-query').value;
  const allow = !!product && $('#allow-alternatives').checked;
  await api('/api/shopping-items', {method: 'POST', body: {
    query, ean: product?.ean || null, quantity: +$('#item-qty').value, unit: $('#item-unit').value,
    remember_quantity: true, allow_alternatives: allow,
    match_mode: product ? (allow ? 'exact-met-equivalenten' : 'strikt-exact') : (intent.match_mode || 'basis'),
    display_name: intent.display_name || product?.name || query, product_family: intent.family || null,
    attributes: intent.attributes || [], exclusions: intent.exclusions || [],
    selected_product_id: product?.product_id || null, selected_name: product?.name || null,
    selected_retailer: product?.retailer || null, selected_image_url: product?.image_url || null,
    selected_product_url: product?.product_url || null,
  }});
  event.target.reset(); $('#item-qty').value = 1; enteredQuery = ''; selectedProduct = null; selectedIntent = null;
  $('#selected-product').hidden = true; $('#product-results').hidden = true; $('#alternatives-label').hidden = true;
  await loadItems();
};

async function loadItems() {
  shoppingItems = await (await api('/api/shopping-items')).json();
  const count = shoppingItems.length; const pending = shoppingItems.filter(item => item.review_required);
  $('#item-count').textContent = count; $('#clear-items').hidden = !count;
  $('#list-summary').textContent = pending.length ? `${pending.length} productnamen controleren voordat je vergelijkt.` : count ? `${count} ${count === 1 ? 'product' : 'producten'} klaar om te vergelijken.` : 'Voeg producten toe om te vergelijken.';
  $('#compare').disabled = !count || pending.length > 0;
  $('#items').innerHTML = count ? shoppingItems.map(item => `<div class="shopping-row">${image(item.selected_image_url, 'item-thumb', item.display_name)}
    <div><strong>${esc(item.display_name)}</strong><div class="muted">${esc(item.match_mode === 'basis' ? 'Basisproduct' : `Voorkeur bij ${item.selected_retailer || 'gekozen winkel'}`)} | ${item.attributes.map(esc).join(' | ') || esc(item.product_family)}</div>${item.review_required ? `<p>Controleer de ingevoerde productnaam. De vergelijking beoordeelt daarna de gevonden artikelen.</p><button type="button" class="link confirm-name" data-id="${item.id}">Naam bevestigen</button>` : ''}</div>
    <button class="link qty-item" data-id="${item.id}" data-query="${esc(item.query)}" data-qty="${item.quantity}" data-unit="${esc(item.unit)}">${item.quantity} ${esc(item.unit)} wijzigen</button>
    <button class="danger-link del-item" data-id="${item.id}">Verwijder</button></div>`).join('') : '<div class="empty-list"><span>🧺</span><strong>Je lijst is leeg</strong><p>Voeg hierboven producten toe.</p></div>';
  $$('.del-item').forEach(button => button.onclick = async () => { await api('/api/shopping-items/' + button.dataset.id, {method: 'DELETE'}); await loadItems(); });
  $$('.qty-item').forEach(button => button.onclick = () => quantityModal(button));
  $$('.confirm-name').forEach(button => button.onclick = async () => {
    const item = shoppingItems.find(row => row.id === +button.dataset.id);
    try {
      await api(`/api/shopping-items/${item.id}/intent`, {method: 'PUT', body: {
        display_name: item.display_name, product_family: item.product_family,
        attributes: item.attributes, exclusions: item.exclusions, match_mode: item.match_mode,
      }});
      await loadItems();
    } catch (error) { toast(error.message); }
  });
}

$('#clear-items').onclick = () => {
  const modal = $('#modal'); $('#modal-content').innerHTML = `<h2>Lijst leegmaken?</h2><p>Alle ${shoppingItems.length} producten worden verwijderd.</p><div class="modal-actions"><button value="cancel" class="quiet">Annuleren</button><button id="confirm-clear" type="button" class="danger-solid">Lijst leegmaken</button></div>`;
  modal.showModal(); $('#confirm-clear').onclick = async () => { await api('/api/shopping-items', {method: 'DELETE'}); modal.close(); $('#scenarios').innerHTML = ''; await loadItems(); };
};

function quantityModal(button) {
  const modal = $('#modal'); $('#modal-content').innerHTML = `<h2>Hoeveelheid wijzigen</h2><label>Hoeveelheid<input id="edit-qty" type="number" min="0.1" max="10000" step="0.1" value="${button.dataset.qty}"></label><label>Eenheid<select id="edit-unit"><option>stuk</option><option>verpakking</option><option>g</option><option>kg</option><option>ml</option><option>liter</option></select></label><div class="modal-actions"><button value="cancel" class="quiet">Annuleren</button><button id="save-qty" type="button" class="primary">Opslaan</button></div>`;
  $('#edit-unit').value = button.dataset.unit; modal.showModal();
  $('#save-qty').onclick = async () => { await api(`/api/shopping-items/${button.dataset.id}/quantity`, {method: 'PUT', body: {quantity: +$('#edit-qty').value, unit: $('#edit-unit').value, remember: true}}); modal.close(); await loadItems(); };
}

function quantityLabel(value, dimension) {
  if (value == null) return '';
  if (dimension === 'weight') return value >= 1000 ? `${value / 1000} kg` : `${value} g`;
  if (dimension === 'package') return `${value} verpakking${value === 1 ? '' : 'en'}`;
  if (dimension === 'volume') return value >= 1000 ? `${value / 1000} liter` : `${value} ml`;
  return `${value} stuks`;
}

function missingHtml(detail) {
  return `<li><strong>${esc(detail.name)}</strong><span>${esc(detail.reasons?.[0]?.message || 'Geen passend aanbod')}${detail.reasons?.[0]?.code === 'quantity_unknown' ? ` Je vraagt ${esc(detail.quantity)} ${esc(detail.unit)}.` : ''}</span><button type="button" class="link review-missing" data-id="${detail.item_id}">Product of hoeveelheid aanpassen</button></li>`;
}

function scenarioHtml(label, scenario, best) {
  if (!scenario) return '';
  const key = `receipt-${++receiptCounter}`;
  receiptScenarios.set(key, {label, scenario});
  return `<article class="scenario ${scenario.complete && scenario.total_cents === best ? 'total-best' : ''} ${scenario.complete ? '' : 'incomplete'}">
    <div class="scenario-head"><div><p class="eyebrow">${esc(label)}</p><h2>${scenario.stores.map(esc).join(' + ')}</h2></div><button class="receipt-button" data-receipt="${key}">Bon / exporteren</button></div>
    <p class="coverage">${scenario.matched_count ?? scenario.offers.length} van ${scenario.requested_count ?? (scenario.offers.length + scenario.missing.length)} regels gevonden${scenario.complete ? '' : ' · onvolledig'}</p>
    <p class="money">${scenario.complete ? euro(scenario.total_cents) : 'Subtotaal ' + euro(scenario.total_cents)}</p><p>${euro(scenario.product_cents)} boodschappen + ${euro(scenario.travel_cents)} reis | ${scenario.duration_minutes} min</p>
    ${(scenario.store_details || []).map(store => `<p class="muted">${esc(store.retailer)} | <a href="${safeUrl(store.map_url)}" target="_blank" rel="noreferrer">${esc(store.address || 'Bekijk op kaart')}</a></p>`).join('')}
    ${scenario.offers.map(offer => `<div class="offer">${image(offer.image_url, 'offer-thumb', offer.product_name)}<span>${offer.product_url ? `<a href="${safeUrl(offer.product_url)}" target="_blank" rel="noreferrer"><strong>${esc(offer.product_name)}</strong></a>` : `<strong>${esc(offer.product_name)}</strong>`}<small>${offer.packages_needed > 1 ? `${offer.packages_needed} verpakkingen | ` : ''}${offer.delivered_amount != null ? `${quantityLabel(offer.delivered_amount, offer.package_dimension)} | ` : ''}${esc(offer.source || '')}${offer.unit_price ? ` | ${esc(offer.unit_price)}` : ''}${offer.loyalty_required ? ' | Klantenkaart vereist' : ''}</small>${offer.promotion ? `<span class="promo-badge">${esc(offer.promotion)}${offer.valid_until ? ' tot ' + esc(offer.valid_until) : ''}</span>` : ''}</span><strong>${euro(offer.total_cents)}</strong></div>`).join('')}
    ${scenario.missing.length ? `<details class="missing-details"><summary>${scenario.missing.length} ontbrekende regels en redenen</summary><ul>${(scenario.missing_details || scenario.missing.map(name => ({name}))).map(missingHtml).join('')}</ul></details>` : ''}</article>`;
}

$('#compare').onclick = async () => {
  try {
    receiptScenarios = new Map(); receiptCounter = 0;
    const result = await (await api('/api/shopping/compare', {method: 'POST', body: {postcode: $('#postcode').value, cost_per_km: +$('#cost-km').value}})).json();
    const recommendations = [result.single, result.double].filter(Boolean); const best = recommendations.length ? Math.min(...recommendations.map(value => value.total_cents)) : null;
    const completeStores = (result.retailers || []).filter(value => value.complete);
    const incompleteStores = (result.retailers || []).filter(value => !value.complete);
    const warning = recommendations.length ? '' : '<div class="comparison-warning"><strong>Geen compleet mandje gevonden</strong><span>De subtotalen hieronder bevatten alleen gevonden producten. Ontbrekende artikelen zijn niet in de prijs inbegrepen.</span></div>';
    const retailerSection = completeStores.length || incompleteStores.length ? `<section class="retailer-comparison"><div class="retailer-heading"><p class="eyebrow">ALLE WINKELS</p><h2>Prijs per supermarkt</h2></div><div class="retailer-grid">${completeStores.map(value => scenarioHtml('Compleet', value, null)).join('')}</div>${incompleteStores.length ? `<details class="incomplete-retailers"><summary>${incompleteStores.length} onvolledige winkels bekijken</summary><div class="incomplete-grid">${incompleteStores.map(value => scenarioHtml('Onvolledig', value, null)).join('')}</div></details>` : ''}</section>` : '';
    const unresolved = (result.unresolved_items || []).length ? `<section class="comparison-issues"><h2>Nog op te lossen</h2><ul>${result.unresolved_items.map(missingHtml).join('')}</ul></section>` : '';
    const partials = (result.diagnostics || []).length ? `<section class="partial-results"><h2>Meeste regels gevonden</h2><p>Gerangschikt op volledigheid, daarna op subtotaal. Dit is geen prijs voor je volledige lijst.</p><div class="retailer-grid">${result.diagnostics.map(value => scenarioHtml(value.stores.length === 1 ? 'Onvolledig · één winkel' : 'Onvolledig · twee winkels', value, null)).join('')}</div></section>` : '';
    const reviews = (result.review_summary || []).length ? `<details class="comparison-review"><summary>Niet alle gevonden productnamen konden automatisch worden beoordeeld</summary><p>Deze kandidaten tellen niet mee in de prijsselectie. Een onbekend merk of een onduidelijke naam kan ook een geldig artikel zijn. Je kunt zelf een concreet product kiezen.</p><ul>${result.review_summary.map(item => `<li>${esc(item.name)}: ${item.count} kandidaten vragen controle <button type="button" class="link review-missing" data-id="${item.item_id}">Product kiezen</button></li>`).join('')}</ul></details>` : '';
    const sourceErrors = (result.source_errors || []).length ? `<p class="comparison-warning">Niet alle bronnen konden worden geraadpleegd: ${[...new Set(result.source_errors.map(error => error.source))].map(esc).join(', ')}. De vergelijking kan daardoor aanbiedingen missen.</p>` : '';
    $('#scenarios').innerHTML = warning + (result.constraint_note ? `<p class="comparison-warning">${esc(result.constraint_note)}</p>` : '') + sourceErrors + unresolved + reviews + scenarioHtml('Een winkel', result.single, best) + scenarioHtml('Twee winkels', result.double, best) + partials + retailerSection + `<p class="fineprint">${esc(result.source_note)} ${esc(result.coverage_note || '')}</p>`;
    $$('.review-missing').forEach(button => button.onclick = () => reviewMissing(+button.dataset.id));
    $$('.receipt-button').forEach(button => button.onclick = () => openReceipt(button.dataset.receipt));
  } catch (error) { toast(error.message); }
};

function openReceipt(key) {
  const entry = receiptScenarios.get(key); if (!entry) return;
  const scenario = entry.scenario; const modal = $('#modal');
  const groups = scenario.stores.map(store => ({store, offers: scenario.offers.filter(offer => offer.retailer === store)})).filter(group => group.offers.length);
  $('#modal-content').innerHTML = `<div class="receipt"><div class="receipt-brand"><span class="receipt-logo">B</span><div><strong>BoodschappenWijzer</strong><small>Prijsvergelijking</small></div></div><div class="receipt-meta"><span>${new Intl.DateTimeFormat('nl-NL', {dateStyle: 'medium', timeStyle: 'short'}).format(new Date())}</span><span>${esc(entry.label)}</span></div><h2>${scenario.stores.map(esc).join(' + ')}</h2>${!scenario.complete ? '<p class="comparison-warning">Onvolledig: ontbrekende artikelen zijn niet in het subtotaal inbegrepen.</p>' : ''}${groups.map(group => `<section class="receipt-store"><h3>${esc(group.store)}</h3>${group.offers.map(offer => `<div class="receipt-line"><div><strong>${esc(offer.product_name)}</strong><small>${offer.packages_needed > 1 ? `${offer.packages_needed} verpakkingen` : offer.delivered_amount != null ? quantityLabel(offer.delivered_amount, offer.package_dimension) : '1 verpakking'}</small></div><span>${euro(offer.total_cents)}</span></div>`).join('')}</section>`).join('')}<div class="receipt-totals"><div><span>Boodschappen</span><strong>${euro(scenario.product_cents)}</strong></div><div><span>Reis</span><strong>${euro(scenario.travel_cents)}</strong></div><div class="receipt-grand"><span>${scenario.complete ? 'Totaal' : 'Subtotaal'}</span><strong>${euro(scenario.total_cents)}</strong></div></div>${scenario.missing.length ? `<section><h3>Nog te kopen</h3><ul>${scenario.missing.map(name => `<li>${esc(name)}</li>`).join('')}</ul></section>` : ''}<p class="receipt-note">Prijsindicatie, geen kassabon. Prijzen kunnen in de winkel afwijken.</p></div><div class="modal-actions receipt-actions"><button value="cancel" class="quiet">Sluiten</button><button id="export-pdf" type="button" class="primary">Download PDF</button><button id="export-png" type="button" class="quiet">Download PNG</button></div>`;
  modal.classList.add('receipt-dialog'); modal.showModal(); modal.addEventListener('close', () => modal.classList.remove('receipt-dialog'), {once: true}); for (const format of ['pdf', 'png']) {
    const button = $(`#export-${format}`);
    button.onclick = async () => {
      button.disabled = true;
      try {
        const response = await api(`/api/shopping/receipt/${format}`, {method: 'POST', body: {stores: scenario.stores}});
        const url = URL.createObjectURL(await response.blob());
        const link = document.createElement('a'); link.href = url; link.download = `boodschappenbon.${format}`;
        document.body.append(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 30000);
      } catch (error) { toast(error.message); }
      finally { button.disabled = false; }
    };
  }
}

loadItems().catch(error => toast(error.message));


async function reviewMissing(itemId) {
  const item = shoppingItems.find(value => value.id === itemId);
  if (!item) return;
  const modal = $('#modal');
  $('#modal-content').innerHTML = `<h2>${esc(item.display_name || item.query)} aanpassen</h2><p>Bevestig een concreet artikel of pas de hoeveelheid aan. Een stuk is één exemplaar; een verpakking kan meerdere stuks bevatten.</p><label>Hoeveelheid<input id="review-qty" type="number" min="0.01" step="any" value="${item.quantity}"></label><label>Eenheid<select id="review-unit">${['stuk', 'verpakking', 'g', 'kg', 'ml', 'liter'].map(unit => `<option ${unit === item.unit ? 'selected' : ''}>${unit}</option>`).join('')}</select></label><button type="button" id="review-quantity" class="quiet">Alleen hoeveelheid opslaan</button><label>Zoek een artikel<input id="review-query" value="${esc(item.query)}"></label><button type="button" id="review-search" class="primary">Zoeken</button><div id="review-results" aria-live="polite"></div><div class="modal-actions"><button value="cancel" class="quiet">Sluiten</button></div>`;
  modal.showModal();
  const quantityBody = () => ({quantity: +$('#review-qty').value, unit: $('#review-unit').value});
  $('#review-quantity').onclick = async () => {
    try {
      await api(`/api/shopping-items/${itemId}/quantity`, {method: 'PUT', body: {...quantityBody(), remember: true}});
      modal.close(); await loadItems(); $('#scenarios').innerHTML = '<p>Hoeveelheid aangepast. Vergelijk opnieuw voor bijgewerkte prijzen.</p>';
    } catch (error) { toast(error.message); }
  };
  $('#review-search').onclick = async () => {
    const box = $('#review-results'); box.textContent = 'Producten zoeken…';
    try {
      const products = await (await api('/api/products/search?q=' + encodeURIComponent($('#review-query').value))).json();
      box.innerHTML = products.length ? `<p>Controleer product en verpakking. Je keuze geldt voor dit exacte artikel bij deze winkel.</p>${products.map((product, index) => `<button type="button" class="product-option review-choice" data-index="${index}"><span><strong>${esc(product.name)}</strong><span>${esc(product.retailer)} | ${esc(product.quantity || 'Inhoud onbekend')}</span></span><strong>${euro(product.price_cents)}</strong></button>`).join('')}` : '<p>Geen bronproducten gevonden. Probeer een andere zoekterm.</p>';
      $$('.review-choice').forEach(button => button.onclick = async () => {
        const product = products[+button.dataset.index];
        try {
          await api(`/api/shopping-items/${itemId}/selection`, {method: 'PUT', body: {
            product_id: product.product_id, name: product.name, retailer: product.retailer,
            image_url: product.image_url, product_url: product.product_url, ...quantityBody(),
          }});
          modal.close(); await loadItems(); $('#scenarios').innerHTML = '<p>Artikel bevestigd. Vergelijk opnieuw voor bijgewerkte prijzen.</p>';
        } catch (error) { toast(error.message); }
      });
    } catch (error) { box.textContent = error.message; }
  };
}
