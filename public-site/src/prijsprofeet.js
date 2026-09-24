/** Pure source adapter. No credentials, persistence or network side effects. */
export const SOURCE = Object.freeze({name: 'PrijsProfeet', url: 'https://www.prijsprofeet.nl'});
const DAY = 86400000;
const retailers = {albert_heijn: 'Albert Heijn', ah: 'Albert Heijn', jumbo: 'Jumbo', plus: 'PLUS',
  aldi: 'ALDI', lidl: 'Lidl', dirk: 'Dirk', ekoplaza: 'Ekoplaza', hoogvliet: 'Hoogvliet',
  dekamarkt: 'DekaMarkt', vomar: 'Vomar'};
const money = n => typeof n === 'number' && Number.isFinite(n) && n > 0 ? Math.round(n * 100) : null;
const text = v => typeof v === 'string' ? v.trim() : '';
function safeUrl(value) {
  try { const u = new URL(value); return u.protocol === 'https:' ? u.href : null; } catch { return null; }
}
function date(value) {
  if (value == null || value === '') return null;
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(value)) return NaN;
  const ms = Date.parse(value);
  if (!Number.isFinite(ms) || new Date(ms).toISOString().slice(0, 10) !== value.slice(0, 10)) return NaN;
  return ms;
}

/** Unknown conditions are reviewable, never a licence to quote an invented regular price. */
export function normalizeProduct(raw, {now = Date.now()} = {}) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new TypeError('Invalid product');
  const name = text(raw.name) || text(raw.title);
  const id = text(raw.product_id);
  const retailerKey = text(raw.retailer).toLowerCase().replace(/[ -]/g, '_');
  if (!name || !id || !retailers[retailerKey]) throw new TypeError('Missing product identity or unknown retailer');
  const issues = [];
  const priceCents = money(raw.price);
  if (!priceCents || priceCents <= 1) issues.push('invalid_price');
  if (raw.currency && raw.currency !== 'EUR') issues.push('unsupported_currency');
  const from = date(raw.valid_from), until = date(raw.valid_until), extracted = date(raw.extracted_at);
  if ([from, until, extracted].some(Number.isNaN)) issues.push('invalid_date');
  // Date-only validity is checked in the retailer's Dutch calendar, not the server timezone.
  const today = new Intl.DateTimeFormat('en-CA', {timeZone: 'Europe/Amsterdam', year: 'numeric', month: '2-digit', day: '2-digit'}).format(now);
  if (from != null && text(raw.valid_from).slice(0, 10) > today) issues.push('upcoming');
  if (until != null && text(raw.valid_until).slice(0, 10) < today) issues.push('expired');
  if (from != null && until != null && from > until) issues.push('invalid_date_range');
  const status = text(raw.promotion_status).toLowerCase();
  if (['upcoming', 'expired', 'historical'].includes(status)) issues.push(status);
  else if (!['active', 'shelf'].includes(status)) issues.push('unknown_price_status');
  if (extracted == null) issues.push('unknown_observation_date');
  else if (extracted > now + 300000 || now - extracted > DAY) issues.push('stale_observation');
  const multiQuantity = raw.multi_buy_quantity;
  const multiPriceCents = money(raw.multi_buy_price);
  const hasMulti = multiQuantity != null || raw.multi_buy_price != null;
  if (hasMulti && (!Number.isInteger(multiQuantity) || multiQuantity < 2 || !multiPriceCents)) issues.push('invalid_multibuy');
  // Promotion formulas are not inferred from marketing text; consumers must handle these explicitly.
  if (raw.is_promotional && status !== 'active') issues.push('inactive_promotion');
  const promotionType = text(raw.promotion_type);
  if (raw.is_promotional && /\b(mix|vanaf|tot|starting|volume)\b/i.test(promotionType)) issues.push('complex_promotion');
  const loyaltyPriceCents = money(raw.loyalty_price);
  const loyaltyProgram = text(raw.loyalty_program);
  // The API's price is the nonmember price; loyalty_price is a separate offer.
  const loyaltyRequired = false;
  if (raw.is_promotional && retailerKey === 'albert_heijn' && !(loyaltyPriceCents && loyaltyProgram)) issues.push('unknown_loyalty_conditions');
  if (raw.max_per_customer != null && (!Number.isInteger(raw.max_per_customer) || raw.max_per_customer < 1)) issues.push('invalid_purchase_limit');
  // A deliberately short cache also crosses no Dutch calendar boundary: expiry is revalidated on use.
  const expiresAt = Math.min(now + 3600000, extracted == null || !Number.isFinite(extracted) ? now : extracted + DAY);
  return {
    source: SOURCE, productId: id, stableId: `${retailerKey}:${text(raw.base_product_id) || id}`,
    retailer: retailers[retailerKey], name, brand: text(raw.brand), ean: text(raw.ean) || null,
    category: text(raw.unified_category), retailer_category: text(raw.retailer_category),
    package: text(raw.quantity), priceCents, originalPriceCents: money(raw.original_price),
    productUrl: safeUrl(raw.product_url), observedAt: extracted, fetchedAt: now, expiresAt,
    validFrom: raw.valid_from ?? null, validUntil: raw.valid_until ?? null, status,
    loyaltyRequired, loyaltyProgram, loyaltyPriceCents: loyaltyProgram && loyaltyPriceCents > 1 ? loyaltyPriceCents : null, onlineOnly: raw.online_only === true,
    inStoreOnly: raw.in_store_only === true, maxPerCustomer: raw.max_per_customer ?? null,
    multiBuy: hasMulti && !issues.includes('invalid_multibuy') ? {quantity: multiQuantity, priceCents: multiPriceCents} : null,
    promotionType, issues: [...new Set(issues)], eligible: issues.length === 0,
  };
}

export function normalizeSearch(payload, {page = 1, now = Date.now()} = {}) {
  if (!payload || !Array.isArray(payload.results) || payload.page !== page ||
      !Number.isInteger(payload.total) || payload.total < 0) throw new TypeError('Invalid search pagination');
  if (!Number.isInteger(payload.page_size) || payload.page_size < 1 || payload.page_size > 100 ||
      payload.results.length > payload.page_size) throw new TypeError('Invalid page size');
  const products = [], rejected = [];
  for (const raw of payload.results) {
    try { products.push(normalizeProduct(raw, {now})); }
    catch (error) { rejected.push({reason: error.message}); }
  }
  const received = (page - 1) * payload.page_size + payload.results.length;
  if (received < payload.total && payload.results.length === 0) throw new TypeError('Incomplete pagination');
  const expectedRows=Math.max(0,Math.min(payload.page_size,payload.total-(page-1)*payload.page_size));
  const paginationConsistent=payload.results.length===expectedRows&&(page===1||expectedRows>0);
  return {products, rejected, total: payload.total, page, pageSize:payload.page_size, paginationConsistent, hasMore: received < payload.total, source: SOURCE};
}

export function basketPrice(product, packages, {loyalty = false, channel = 'store', now = Date.now()} = {}) {
  if (!Number.isInteger(packages) || packages < 1) return {reason: 'invalid_quantity'};
  if (!product.eligible) return {reason: product.issues[0]};
  if (now >= product.expiresAt) return {reason: 'stale_price'};
  const today = new Intl.DateTimeFormat('en-CA', {timeZone: 'Europe/Amsterdam', year: 'numeric', month: '2-digit', day: '2-digit'}).format(now);
  if (product.validUntil && product.validUntil.slice(0, 10) < today) return {reason: 'expired'};
  if (product.loyaltyRequired && !loyalty) return {reason: 'loyalty_required'};
  if ((product.onlineOnly && channel === 'store') || (product.inStoreOnly && channel === 'online')) return {reason: 'wrong_channel'};
  if (product.maxPerCustomer && packages > product.maxPerCustomer) return {reason: 'purchase_limit'};
  const multi = product.multiBuy;
  // Avoid treating a per-item multibuy advertised price as the unconditional remainder price.
  if (multi && packages % multi.quantity !== 0) return {reason: 'multibuy_remainder_unverified'};
  const regularTotal = multi ? packages / multi.quantity * multi.priceCents : packages * product.priceCents;
  // Do not combine a separate member price with a bundle whose membership
  // semantics are unspecified. The verified regular bundle remains available.
  if (loyalty && !multi && product.loyaltyPriceCents > 1 && product.loyaltyPriceCents < product.priceCents) {
    return {totalCents: packages * product.loyaltyPriceCents, loyaltyApplied:true};
  }
  return {totalCents: regularTotal};
}
