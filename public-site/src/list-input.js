import { MAX_ITEMS } from "./list-store.js";
const aliases = {
  gram: "g",
  gr: "g",
  g: "g",
  kg: "kg",
  kilo: "kg",
  liter: "l",
  liters: "l",
  ltr: "l",
  l: "l",
  ml: "ml",
  st: "stuk",
  stuk: "stuk",
  stuks: "stuk",
  pak: "verpakking",
  pakken: "verpakking",
  verpakking: "verpakking",
  verpakkingen: "verpakking",
  blik: "verpakking",
  blikken: "verpakking",
  fles: "verpakking",
  flessen: "verpakking",
  zak: "verpakking",
  zakken: "verpakking",
  pot: "verpakking",
  potten: "verpakking",
};
const unitPattern = Object.keys(aliases)
  .sort((a, b) => b.length - a.length)
  .join("|");
const explicit = new RegExp(
  `^(\\d+(?:[.,]\\d+)?)\\s*(${unitPattern})\\b\\s*(?:van\\s+)?(.+)$`,
  "i",
);
const suffix = new RegExp(
  `^(.+?)\\s+(\\d+(?:[.,]\\d+)?)\\s*(${unitPattern})$`,
  "i",
);
const number = (s) => Number(s.replace(",", "."));
export function parseList(
  text,
  { id = () => crypto.randomUUID(), metadata = false } = {},
) {
  if (typeof text !== "string" || text.length > 30000)
    throw new Error("De lijst is te groot. Gebruik maximaal 200 regels.");
  const lines = text
    .normalize("NFKC")
    .replace(/[\u200b-\u200f\u2060\ufeff]/g, "")
    .split(/\r?\n/)
    .map((line) => line.replace(/^\s*(?:[•●▪*]\s*|-\s+)/, "").trim())
    .filter(Boolean);
  if (lines.length > MAX_ITEMS)
    throw new Error("Gebruik maximaal 200 regels per lijst.");
  return lines.map((line) => {
    if (/^-\d/.test(line))
      throw new Error("Een hoeveelheid moet groter zijn dan nul.");
    let query = line,
      quantity = 1,
      unit = "verpakking";
    let match;
    // "2 x 400 ml kokosmelk" asks for 800 ml; the selected pack size may differ.
    const multi = line.match(
      /^(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*(g|gr|gram|kg|ml|l|liter)\b\s+(.+)$/i,
    );
    if (multi) {
      quantity = Number(multi[1]) * number(multi[2]);
      unit = aliases[multi[3].toLowerCase()];
      query = multi[4];
    } else if ((match = line.match(explicit))) {
      quantity = number(match[1]);
      unit = aliases[match[2].toLowerCase()];
      query = match[3];
    } else if ((match = line.match(suffix))) {
      query = match[1];
      quantity = number(match[2]);
      unit = aliases[match[3].toLowerCase()];
    } else if ((match = line.match(/^(\d+(?:[.,]\d+)?)\s*[x×]\s+(.+)$/i))) {
      quantity = number(match[1]);
      query = match[2];
    } else if ((match = line.match(/^(\d+(?:[.,]\d+)?)\s+(.+)$/))) {
      quantity = number(match[1]);
      query = match[2];
      unit = "stuk";
    }
    query = query.trim();
    if (
      !query ||
      query.length > 150 ||
      /[\x00-\x1f]/.test(query) ||
      !Number.isFinite(quantity) ||
      quantity <= 0 ||
      quantity > 100000
    ) {
      throw new Error(`Controleer deze regel: ${line.slice(0, 100)}`);
    }
    // Repeated lines stay separate; silently doubling or deleting them guesses the user's intent.
    return {
      id: id(),
      query,
      quantity,
      unit,
      ...(metadata ? { explicit: !!(multi || match), sourceText: line } : {}),
    };
  });
}
