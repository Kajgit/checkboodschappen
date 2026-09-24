import { parseList } from "./list-input.js";
// Optional shopping proposals, not recipe quantities. Names remain untouched.
// Anchored names prevent 'tomatenpuree' or 'gehaktkruiden' taking a fresh-food quantity.
const proposals = [
  [
    /^(?:biologische?\s+)?(?:runder|half.om.half|vegetarisch|vegan)?\s*gehakt$/i,
    125,
    "g",
  ],
  [/^(?:biologische?\s+)?(?:kipfilet|kipdijfilet|shoarmavlees)$/i, 125, "g"],
  [/^(?:kruimige?\s+|vastkokende?\s+)?aardappel(?:en|s)?$/i, 250, "g"],
  [/^(?:sperziebonen|snijbonen)$/i, 200, "g"],
  [/^(?:tomaat|tomaten)$/i, 150, "g"],
  [/^komkommer(?:s)?$/i, 0.5, "stuk"],
  [/^paprika(?:s|’s|'s)?$/i, 0.5, "stuk"],
  [/^(?:geraspte\s+)?kaas$/i, 60, "g"],
  [/^(?:griekse\s+)?yoghurt$/i, 250, "g"],
  [/^(?:hamburger|slavink)(?:s|en)?$/i, 1, "stuk"],
  [/^(?:basmati\s*|zilvervlies\s*|witte\s+)?rijst$/i, 75, "g"],
  [/^(?:pasta|spaghetti|penne|macaroni)$/i, 100, "g"],
];
const directive =
  /\b(?:voor\s+)?(\d+(?:[.,]\d+)?)\s*(?:personen|persoon|pers\.?|p)\b/gi;
function personCount(value) {
  const n = Number(value);
  if (!Number.isInteger(n) || n < 1 || n > 12)
    throw Error("Kies 1 tot en met 12 personen.");
  return n;
}
export function interpretList(text, { people = null, id } = {}) {
  if (typeof text !== "string" || text.length > 30000)
    throw Error("Gebruik maximaal 200 regels.");
  const normalized = text
    .normalize("NFKC")
    .replace(/[\u200b-\u200f\u2060\ufeff]/g, "");
  const found = [...normalized.matchAll(directive)].map((m) =>
    personCount(m[1]),
  );
  const counts = [...new Set(found)];
  if (counts.length > 1)
    throw Error(
      "Er staan verschillende aantallen personen in je tekst. Controleer één lijst per keer.",
    );
  const selected =
    counts[0] ?? (people == null || people === "" ? null : personCount(people));
  const clean = normalized
    .split(/\r?\n/)
    .map((line) => {
      if (![...line.matchAll(directive)].length) return line;
      const remaining = line
        .replace(directive, "")
        .replace(/^\s*[•●▪*]\s*/, "")
        .replace(/[\s:;,.()\-]+$/, "")
        .trim();
      return /^(?:boodschappen(?:lijst)?|lijst|ingrediënten|ingredienten)?$/i.test(
        remaining,
      )
        ? ""
        : remaining;
    })
    .filter((line) => line.trim())
    .join("\n");
  const rows = parseList(clean, { id, metadata: true }).map((item) => {
    if (item.explicit) return { ...item, kind: "explicit", note: "Opgegeven" };
    if (selected) {
      const rule = proposals.find(([pattern]) => pattern.test(item.query));
      if (rule) {
        const amount = rule[1] * selected;
        return {
          ...item,
          quantity:
            rule[2] === "stuk" ? Math.max(1, Math.ceil(amount)) : amount,
          unit: rule[2],
          kind: "estimate",
          note: `Voorstel · ${selected} personen`,
        };
      }
      if (
        /^(?:taco\s*shells?|tacoschelpen|tortilla[’'s]*|wraps)(?:\s*\/\s*(?:tortilla[’'s]*|wraps))?$/i.test(
          item.query,
        )
      )
        return {
          ...item,
          quantity: Math.ceil(selected / 4),
          kind: "estimate",
          note: `Voorstel · ${selected} personen`,
        };
    }
    return {
      ...item,
      kind: "package",
      note: "Geen hoeveelheid · 1 verpakking",
    };
  });
  return { people: selected, rows };
}
