import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ShoppingBasket,
  ArrowRight,
  Download,
  Upload,
  Trash2,
  MapPin,
  SlidersHorizontal,
  ListChecks,
  FileText,
  Image,
  ChevronDown,
  LoaderCircle,
  Check,
} from "lucide-react";
import { Button } from "./components/ui/button";
import { Input } from "./components/ui/input";
import { Textarea } from "./components/ui/textarea";
import {
  ListStore,
  emptyList,
  parseBackup,
  serializeBackup,
  validateList,
} from "./list-store.js";
import { interpretList } from "./list-interpretation.js";
import { loadAvailableCatalogue } from "./checkjebon.js";
import { MatcherClient } from "./matcher-client.js";

import {
  locatePostcode,
  normalizePostcode,
  validateStores,
} from "./locations.js";
import { runComparison } from "./comparison.js";
import {safeProductUrl,shopMapUrl,shopDirectionsUrl} from "./links.js";
import { reasons } from "./reasons.js";
const store = new ListStore(),
  money = (n) =>
    new Intl.NumberFormat("nl-NL", {
      style: "currency",
      currency: "EUR",
    }).format(n / 100);
const units = [
  ["verpakking", "verp."],
  ["stuk", "stuks"],
  ["g", "gram"],
  ["kg", "kg"],
  ["ml", "ml"],
  ["l", "liter"],
];
function Credit({ source }) {
  return (
    <a
      className="source-link"
      href={source.url}
      target="_blank"
      rel="noopener noreferrer"
    >
      {source.name}
    </a>
  );
}
function Basket({ basket, result, index, onStatus }) {
  const [exporting, setExporting] = useState("");
  async function exportBon(format) {
    setExporting(format);
    try {
      const { downloadReceipt } = await import("./receipt.js");
      const out = await downloadReceipt(
        {
          ...basket,
          missing: basket.missing.map((m) => ({
            ...m,
            reason: reasons[m.reason] || m.reason,
          })),
        },
        result,
        format,
      );
      onStatus(
        out.filename.endsWith(".zip")
          ? `${out.pages} PNG-pagina’s gedownload als ZIP.`
          : "Bon gedownload.",
      );
    } catch (e) {
      onStatus(e.message);
    } finally {
      setExporting("");
    }
  }
  return (
    <article
      className={`basket ${index === 0 && basket.complete ? "best-basket" : ""}`}
    >
      <div className="basket-top">
        <div>
          <div className="flex items-center gap-2">
            <h3>{basket.retailer}</h3>
            {index === 0 && basket.complete && (
              <span className="badge">Laagste gevonden prijs</span>
            )}
          </div>
          <p className={basket.complete ? "coverage" : "missing"}>
            {basket.complete ? <Check size={13} /> : null}
            {basket.lines.length}/{result.itemCount} producten ·{" "}
            {basket.stores.length}{" "}
            {basket.stores.length === 1 ? "winkel" : "winkels"}
          </p>
        </div>
        <div className="price">
          {money(basket.totalWithTravelCents)}
          <span>{basket.complete ? "totaal" : "gedeeltelijk"}</span>
        </div>
      </div>
      <div className="basket-meta">
        <MapPin size={13} />
        {basket.travelDistanceKm.toFixed(1)} km hemelsbreed heen en terug
        {basket.travelCents > 0 &&
          ` · incl. ${money(basket.travelCents)} reiskosten`}
      </div>
      <div className="shop-links">{basket.stores.map(s=><div key={s.id}><span>{s.name}{s.address?` · ${s.address}`:''}</span><a href={shopMapUrl(s)} target="_blank" rel="noopener noreferrer">Kaart ↗</a>{shopDirectionsUrl(s)&&<a href={shopDirectionsUrl(s)} target="_blank" rel="noopener noreferrer">Route ↗</a>}</div>)}</div>
      <details className="basket-details" open={index === 0}>
        <summary>
          Producten en winkels <ChevronDown size={14} />
        </summary>
        <div>
          {basket.lines.map((line) => (
            <div className="product-line" key={line.item.id}>
              <div className="line-title">
                <strong>{line.item.query}</strong>
                <strong>{money(line.totalCents)}</strong>
              </div>
              <p>
                {line.product.retailer} · {safeProductUrl(line.product.productUrl)?<a className="product-link" href={safeProductUrl(line.product.productUrl)} target="_blank" rel="noopener noreferrer">{line.product.name} ↗</a>:line.product.name}
              </p>
              <small>
                {line.decision.packages} verp. ×{" "}
                {line.product.package || "inhoud onbekend"} · gevraagd:{" "}
                {line.item.quantity} {line.item.unit}
              </small>
              {line.decision.overage > 0 && (
                <small>
                  Extra: {Number(line.decision.overage.toFixed(3))}{" "}
                  {
                    {
                      weight: "g",
                      volume: "ml",
                      count: "stuks",
                      package: "verp.",
                    }[line.decision.dimension]
                  }
                </small>
              )}
              {line.product.loyaltyRequired && (
                <small className="missing">
                  Ledenprijs ·{" "}
                  {line.product.loyaltyProgram || "klantenkaart vereist"}
                </small>
              )}
              {line.product.maxPerCustomer && (
                <small>
                  Max. {line.product.maxPerCustomer} verp. per klant, over alle
                  regels samen.
                </small>
              )}
              {line.decision.promotionExtraPackages > 0 && (
                <small>
                  Voor de actie: {line.decision.promotionExtraPackages} extra
                  verp.
                </small>
              )}
              <div className="product-links"><Credit source={line.product.source} />{!safeProductUrl(line.product.productUrl)&&<span>Geen productlink beschikbaar</span>}</div>
            </div>
          ))}
          {basket.missing.length > 0 && (
            <div className="missing-box">
              <strong>{basket.missing.length} niet gevonden</strong>
              {basket.missing.map((m) => (
                <p key={m.item.id}>
                  {m.item.query} — {reasons[m.reason] || m.reason}
                </p>
              ))}
            </div>
          )}

        </div>
      </details>
      <div className="export-row">
        <span>Bewaar je bon</span>
        <Button
          variant="ghost"
          size="sm"
          disabled={!!exporting}
          onClick={() => exportBon("pdf")}
        >
          <FileText />
          PDF
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={!!exporting}
          onClick={() => exportBon("png")}
        >
          <Image />
          PNG
        </Button>
        {exporting && <LoaderCircle className="animate-spin" size={14} />}
      </div>
    </article>
  );
}
function App() {
  const [list, setList] = useState(emptyList),
    [ready, setReady] = useState(false),
    [text, setText] = useState(""),
    [people, setPeople] = useState(""),
    [review, setReview] = useState(null),
    [postcode, setPostcode] = useState(""),
    [radius, setRadius] = useState(10),
    [maxStores, setMaxStores] = useState(2),
    [travel, setTravel] = useState(0),
    [loyalty, setLoyalty] = useState(false),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("Lijst laden…"),
    [result, setResult] = useState(null),
    [progress, setProgress] = useState(0);
  const current = useRef(list),
    queue = useRef(Promise.resolve()),
    run = useRef(null),
    file = useRef(null);
  useEffect(() => {
    let alive = true;
    store
      .load()
      .then((data) => {
        if (alive) {
          current.current = data;
          setList(data);
          setPostcode(data.postcode);
          setReady(true);
          setMessage("");
        }
      })
      .catch((e) => {
        if (alive) setMessage(e.message);
      });
    return () => {
      alive = false;
      run.current?.controller.abort();
      run.current?.matcher.close();
    };
  }, []);
  function invalidate() {
    setResult(null);
    setMessage("Lijst gewijzigd. Vergelijk opnieuw.");
  }
  function save(change) {
    invalidate();
    queue.current = queue.current
      .then(async () => {
        const next = validateList(change(structuredClone(current.current)));
        await store.save(next);
        current.current = next;
        setList(next);
        return true;
      })
      .catch((e) => {
        setMessage(e.message);
        setList({ ...current.current });
        return false;
      });
    return queue.current;
  }
  function prepare(e) {
    e.preventDefault();
    try {
      const proposal = interpretList(text, { people });
      setPeople(proposal.people == null ? "" : String(proposal.people));
      setReview({
        ...proposal,
        rows: proposal.rows.map((row) => ({ ...row, selected: true })),
      });
      setMessage("");
    } catch (e) {
      setMessage(e.message);
    }
  }
  function editReview(id, key, value) {
    setReview((previous) => ({
      ...previous,
      rows: previous.rows.map((row) =>
        row.id === id
          ? {
              ...row,
              [key]: value,
              ...(["quantity", "unit"].includes(key)
                ? { note: "Aangepast" }
                : {}),
            }
          : row,
      ),
    }));
  }
  async function add() {
    if (!review) return;
    const items = review.rows
      .filter((row) => row.selected)
      .map(({ id, query, quantity, unit }) => ({
        id,
        query,
        quantity: Number(quantity),
        unit,
      }));
    if (
      items.length &&
      (await save((next) => ({ ...next, items: [...next.items, ...items] })))
    ) {
      setText("");
      setReview(null);
      setMessage(`${items.length} producten toegevoegd.`);
    }
  }
  function edit(id, key, value) {
    save((next) => {
      next.items.find((i) => i.id === id)[key] =
        key === "quantity" ? Number(value) : value;
      return next;
    });
  }
  async function backup() {
    await queue.current;
    const url = URL.createObjectURL(
      new Blob([serializeBackup(current.current)], {
        type: "application/json",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "boodschappenlijst.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function importList(e) {
    const input = e.target;
    try {
      const f = input.files[0];
      if (!f) return;
      if (f.size > 100000) throw Error("Het lijstbestand is te groot.");
      const data = parseBackup(await f.text());
      if (
        current.current.items.length &&
        !confirm("Vervang je huidige lijst door dit bestand?")
      )
        return;
      if (await save(() => data)) setPostcode(data.postcode);
    } catch (e) {
      setMessage(e.message);
    } finally {
      input.value = "";
    }
  }
  async function compare() {
    if (busy) return;
    setBusy(true);
    setResult(null);
    setProgress(0);
    const controller = new AbortController();
    let matcher;
    try {
      if ((await queue.current) === false) return;
      const normalized = normalizePostcode(postcode);
      if (!(await save((next) => ({ ...next, postcode: normalized })))) return;
      matcher = new MatcherClient();
      run.current = { controller, matcher };
      setMessage("Winkels en prijzen ophalen…");
      const [catalogue, origin, response] = await Promise.all([
        loadAvailableCatalogue({ signal: controller.signal }),
        locatePostcode(normalized, { signal: controller.signal }),
        fetch("/generated/stores.json", { signal: controller.signal }),
      ]);
      if (!response.ok) throw Error("Het winkelbestand is niet beschikbaar.");
      const stores = validateStores(await response.json());
      const data = await runComparison(
        current.current.items,
        catalogue,
        matcher,
        {
          signal: controller.signal,
          loyalty,
          finalize: (items, matched, options) => {
            setMessage("Winkelmandjes berekenen…");
            return matcher.request("finalize", {
              items,
              matched,
              options,
              origin,
              stores,
              locationOptions: {
                radius: Number(radius),
                maxStores: Number(maxStores),
                costPerKm: Number(travel),
              },
            });
          },
          onProgress: ({ done, total }) => {
            setProgress((done / total) * 100);
            setMessage(`${done} van ${total} producten gecontroleerd`);
          },
        },
      );
      setResult(data);
      setMessage("Vergelijking bijgewerkt.");
    } catch (e) {
      setMessage(
        controller.signal.aborted
          ? "Vergelijken gestopt. Je lijst is bewaard."
          : e.message,
      );
    } finally {
      matcher?.close();
      run.current = null;
      setBusy(false);
    }
  }
  return (
    <>
      <header className="app-header">
        <div className="header-inner">
          <a href="/" className="brand">
            <img src="/favicon.png" alt="" width="30" height="30" className="nav-logo" />
            Checkboodschappen
          </a>
          <nav className="header-actions" aria-label="Hoofdnavigatie">
            <a href="/roadmap" className="roadmap-nav-link">Roadmap</a>
            <Button asChild variant="ghost" size="icon">
              <a href="https://github.com/Kajgit/checkboodschappen" target="_blank" rel="noopener noreferrer" aria-label="GitHub repository" title="GitHub">
              <svg className="github-icon" width="26" height="26" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 .75a11.25 11.25 0 0 0-3.56 21.92c.56.1.77-.24.77-.54v-2.1c-3.13.68-3.79-1.33-3.79-1.33-.51-1.3-1.25-1.65-1.25-1.65-1.02-.7.08-.69.08-.69 1.13.08 1.73 1.16 1.73 1.16 1 1.72 2.63 1.22 3.27.93.1-.73.39-1.22.71-1.5-2.5-.28-5.13-1.25-5.13-5.57 0-1.23.44-2.23 1.16-3.02-.12-.28-.5-1.43.11-2.98 0 0 .95-.3 3.09 1.15a10.77 10.77 0 0 1 5.62 0c2.14-1.45 3.08-1.15 3.08-1.15.62 1.55.24 2.7.12 2.98.72.79 1.16 1.79 1.16 3.02 0 4.33-2.63 5.28-5.14 5.56.4.35.76 1.03.76 2.08v3.11c0 .3.2.65.78.54A11.25 11.25 0 0 0 12 .75Z" /></svg>
              </a>
            </Button>
          </nav>
        </div>
      </header>
      <main className="app-main">
        <div className="page-heading">
          <div>
            <h1>Boodschappen vergelijken</h1>
          </div>
        </div>
        <div className="workspace">
          <section className="list-panel panel">
            <div className="panel-heading">
              <h2>
                Mijn boodschappen{" "}
                <span className="count">{list.items.length}</span>
              </h2>
              <div className="flex gap-1">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  title="Lijst bewaren als bestand"
                  aria-label="Lijst bewaren als bestand"
                  onClick={backup}
                  disabled={!ready}
                >
                  <Download />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  title="Lijst importeren"
                  aria-label="Lijst importeren"
                  disabled={!ready || busy}
                  onClick={() => file.current.click()}
                >
                  <Upload />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  title="Lijst wissen"
                  aria-label="Lijst wissen"
                  disabled={!ready || busy || !list.items.length}
                  onClick={() => {
                    if (confirm("Je lijst en postcode wissen?"))
                      save(() => emptyList()).then((ok) => {
                        if (ok) setPostcode("");
                      });
                  }}
                >
                  <Trash2 />
                </Button>
                <input
                  ref={file}
                  type="file"
                  accept=".json,application/json"
                  hidden
                  onChange={importList}
                />
              </div>
            </div>
            <form onSubmit={prepare} className="add-form">
              <label htmlFor="list-input">Producten toevoegen</label>
              <Textarea
                id="list-input"
                rows={3}
                placeholder={"Bijv. 800 ml kokosmelk\nTortilla’s\n500 g gehakt"}
                value={text}
                onChange={(e) => {
                  setText(e.target.value);
                  setReview(null);
                }}
                disabled={!ready || busy}
              />
              <div className="add-bottom">
                <label className="people-field" htmlFor="people">
                  Hoeveelheden voor
                  <select
                    id="people"
                    value={people}
                    disabled={!ready || busy}
                    onChange={(e) => {
                      setPeople(e.target.value);
                      setReview(null);
                    }}
                  >
                    <option value="">Zelf invullen</option>
                    {Array.from({ length: 12 }, (_, i) => i + 1).map((n) => (
                      <option key={n} value={n}>
                        {n} {n === 1 ? "persoon" : "personen"}
                      </option>
                    ))}
                  </select>
                </label>
                <Button
                  size="sm"
                  type="submit"
                  disabled={!ready || busy || !text.trim()}
                >
                  Controleren
                </Button>
              </div>
            </form>
              {review && (
                <div className="review-panel">
                  <h3>Controleer je lijst</h3>
                  <p>
                    {review.people
                      ? `Voorstellen voor ${review.people} personen. Pas ze aan aan je gerecht.`
                      : "Vul ontbrekende hoeveelheden in of kies 1 verpakking."}
                  </p>
                  {review.rows.map((row, index) => (
                    <div className="review-item" key={row.id}>
                      <label className="review-selection">
                        <input
                          type="checkbox"
                          checked={row.selected}
                          disabled={busy}
                          onChange={(e) =>
                            editReview(row.id, "selected", e.target.checked)
                          }
                        />
                        <span>
                          {row.query}
                          <small>{row.note}</small>
                        </span>
                      </label>
                      <div className="review-amount">
                        <Input
                          aria-label={`Voorstel hoeveelheid ${index + 1}`}
                          type="number"
                          min="0.001"
                          max="100000"
                          step="any"
                          value={row.quantity}
                          disabled={busy || !row.selected}
                          onChange={(e) =>
                            editReview(row.id, "quantity", e.target.value)
                          }
                        />
                        <select
                          aria-label={`Voorstel eenheid ${index + 1}`}
                          value={row.unit}
                          disabled={busy || !row.selected}
                          onChange={(e) =>
                            editReview(row.id, "unit", e.target.value)
                          }
                        >
                          {units.map(([value, label]) => (
                            <option key={value} value={value}>
                              {label}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                  ))}
                  {!review.rows.length && (
                    <p>Voeg eerst producten toe aan je tekst.</p>
                  )}
                  <Button
                    type="button"
                    size="sm"
                    disabled={busy || !review.rows.some((row) => row.selected)}
                    onClick={add}
                  >
                    Toevoegen aan lijst
                  </Button>
                </div>
              )}
            <div className="list-table">
              <div className="list-columns">
                <span>Product</span>
                <span>Aantal</span>
                <span>Eenheid</span>
                <span />
              </div>
              {list.items.length ? (
                list.items.map((item, i) => (
                  <div
                    className="item-row"
                    key={`${item.id}:${item.query}:${item.quantity}:${item.unit}`}
                  >
                    <Input
                      aria-label={`Product regel ${i + 1}`}
                      defaultValue={item.query}
                      disabled={busy}
                      onInput={invalidate}
                      onBlur={(e) => {
                        if (e.target.value !== item.query)
                          edit(item.id, "query", e.target.value);
                      }}
                    />
                    <Input
                      aria-label={`Hoeveelheid regel ${i + 1}`}
                      type="number"
                      min="0.001"
                      max="100000"
                      step="any"
                      defaultValue={item.quantity}
                      disabled={busy}
                      onInput={invalidate}
                      onBlur={(e) => {
                        if (Number(e.target.value) !== item.quantity)
                          edit(item.id, "quantity", e.target.value);
                      }}
                    />
                    <select
                      aria-label={`Eenheid regel ${i + 1}`}
                      value={item.unit}
                      disabled={busy}
                      onChange={(e) => edit(item.id, "unit", e.target.value)}
                    >
                      {units.map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`${item.query} verwijderen`}
                      disabled={busy}
                      onClick={() =>
                        save((next) => ({
                          ...next,
                          items: next.items.filter((x) => x.id !== item.id),
                        }))
                      }
                    >
                      <Trash2 size={14} />
                    </Button>
                  </div>
                ))
              ) : (
                <div className="empty-list">
                  <ListChecks size={22} />
                  <p>Je lijst is nog leeg</p>
                  <small>Typ of plak hierboven wat je nodig hebt.</small>
                </div>
              )}
            </div>
            <div className="compare-settings">
              <div className="settings-fields">
                <label htmlFor="postcode">
                  Postcode
                  <Input
                    id="postcode"
                    autoComplete="postal-code"
                    placeholder="1012 JS"
                    maxLength={7}
                    value={postcode}
                    disabled={busy}
                    onChange={(e) => {
                      setPostcode(e.target.value);
                      invalidate();
                    }}
                    onBlur={() => {
                      try {
                        const v = postcode.trim()
                          ? normalizePostcode(postcode)
                          : "";
                        save((next) => ({ ...next, postcode: v }));
                      } catch (e) {
                        setMessage(e.message);
                      }
                    }}
                  />
                </label>
                <label htmlFor="radius">
                  Afstand
                  <select
                    id="radius"
                    value={radius}
                    disabled={busy}
                    onChange={(e) => {
                      setRadius(e.target.value);
                      invalidate();
                    }}
                  >
                    {[5, 10, 20, 50].map((n) => (
                      <option key={n} value={n}>
                        {n} km
                      </option>
                    ))}
                  </select>
                </label>
                <label htmlFor="max-stores">Max. winkels
                  <select id="max-stores" value={maxStores} disabled={busy} onChange={(e) => {setMaxStores(Number(e.target.value)); invalidate();}}>
                    {[1, 2, 3, 4].map(n => <option key={n} value={n}>{n} {n === 1 ? "winkel" : "winkels"}</option>)}
                  </select>
                </label>
              </div>
              <details className="settings-extra">
                <summary>
                  <SlidersHorizontal size={14} />
                  Extra instellingen
                  <ChevronDown size={13} />
                </summary>
                <label htmlFor="travel-cost">
                  Reiskosten per km (€)
                  <Input
                    id="travel-cost"
                    type="number"
                    min="0"
                    max="5"
                    step="0.01"
                    value={travel}
                    disabled={busy}
                    onChange={(e) => {
                      setTravel(e.target.value);
                      invalidate();
                    }}
                  />
                </label>
                <p className="hint">
                  Afstanden zijn hemelsbreed vanaf het postcodecentrum; geen
                  rijroutes. Bij € 0 tellen alleen productprijzen.
                </p>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={loyalty}
                    disabled={busy}
                    onChange={(e) => {
                      setLoyalty(e.target.checked);
                      invalidate();
                    }}
                  />
                  Ledenprijzen meenemen — ik heb de benodigde klantenkaarten
                </label>
              </details>
              <Button
                className="w-full"
                disabled={!ready || busy || !list.items.length}
                onClick={compare}
              >
                {busy ? (
                  <LoaderCircle className="animate-spin" />
                ) : (
                  <ShoppingBasket />
                )}
                {busy ? "Prijzen vergelijken…" : "Vergelijk boodschappen"}
                {!busy && <ArrowRight className="ml-auto" />}
              </Button>
              {busy && (
                <Button
                  variant="ghost"
                  className="w-full mt-2"
                  onClick={() => {
                    run.current?.controller.abort();
                    run.current?.matcher.close();
                  }}
                >
                  Stoppen
                </Button>
              )}
            </div>
          </section>
          <section className="results-panel" aria-label="Vergelijking">
            <div className="result-heading">
              <h2>Vergelijking</h2>
              <span>
                {result ? `${result.baskets.length} opties` : `Max. ${maxStores} ${Number(maxStores) === 1 ? "winkel" : "winkels"}`}
              </span>
            </div>
            <div
              role="status"
              aria-live="polite"
              className={`status-message ${message ? "" : "hidden"}`}
            >
              {busy && <LoaderCircle className="animate-spin" size={14} />}{" "}
              {message}
            </div>
            {busy && (
              <div className="progress">
                <div style={{ width: `${progress}%` }} />
              </div>
            )}
            {!result && !busy && (
              <div className="results-empty panel">
                <h3>Nog geen vergelijking</h3>
                <p>Voeg producten toe en vul je postcode in.</p>
              </div>
            )}
            {result && (
              <>
                <p className="result-location">
                  <MapPin size={14} />
                  {result.location.origin.label} · binnen{" "}
                  {result.location.radius} km
                </p>
                {!result.searchComplete && (
                  <details className="source-notice">
                    <summary>
                      Bronnen en volledigheid{" "}
                      <ChevronDown size={13} />
                    </summary>
                    <p>Prijzen van beschikbare bronnen zijn meegenomen. De vergelijking kan daardoor aanbiedingen missen.</p>
                    {result.sourceIssues.map((s, i) => (
                      <p key={i}>{s}</p>
                    ))}
                  </details>
                )}
                {result.location.stale && (
                  <p className="missing-box">
                    Winkelbestand ouder dan 30 dagen. Controleer de vestiging.
                  </p>
                )}
                {!result.baskets.length && (
                  <p className="panel p-4">
                    Geen passende producten gevonden. Controleer je lijst en
                    bronmeldingen.
                  </p>
                )}
                {result.baskets.map((b, i) => (
                  <Basket
                    key={b.retailer}
                    basket={b}
                    result={result}
                    index={i}
                    onStatus={setMessage}
                  />
                ))}
                <details className="method-note">
                  <summary>Over deze vergelijking</summary>
                  <p>
                    Productregels zijn apart geprijsd; kortingen over meerdere
                    regels worden niet samengevoegd. Afstanden zijn hemelsbreed.
                    Winkelbestand:{" "}
                    {new Date(result.location.sourceDate).toLocaleDateString(
                      "nl-NL",
                    )}
                    .
                  </p>
                  {result.excludedRetailers.length > 0 && (
                    <p>
                      Geen gekoppelde vestiging binnen deze afstand:{" "}
                      {result.excludedRetailers.join(", ")}. Er kan wel een
                      winkel zijn.
                    </p>
                  )}
                </details>
              </>
            )}
          </section>
        </div>
        <footer className="app-footer">
          <div>
            <p>
              Prijzen van <a href="https://www.checkjebon.nl/">Checkjebon</a> en{" "}
              <a href="https://www.prijsprofeet.nl/">PrijsProfeet</a>.
            </p>
            <p>
              Indicatieve prijzen. Controleer prijs en voorraad in de winkel.
              Geen band met de genoemde supermarkten.
            </p>
          </div>
          <div>
            <a href="/privacy.html">Privacy</a>
            <a href="/LICENSE.txt">Licentie</a>
            <a href="/THIRD-PARTY-NOTICES.txt">Bronlicenties</a>
            <a href="https://www.openstreetmap.org/copyright">
              © OpenStreetMap (ODbL)
            </a>
            <a href="https://www.pdok.nl/">PDOK / BAG</a>
            <a href="/generated/stores.json">Winkelbestand</a>
          </div>
        </footer>
      </main>
    </>
  );
}
createRoot(document.getElementById("root")).render(<App />);
