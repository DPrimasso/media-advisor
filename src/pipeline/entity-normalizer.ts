/**
 * Step 4 — Entity normalization.
 * Alias → canonical_name.
 */

const ALIASES: Record<string, string> = {
  inter: "Inter",
  internazionale: "Inter",
  nerazzurri: "Inter",
  "inter milan": "Inter",
  napoli: "Napoli",
  azzurri: "Napoli",
  "ssc napoli": "Napoli",
  juve: "Juventus",
  juventus: "Juventus",
  "la juve": "Juventus",
  bianconeri: "Juventus",
  milan: "Milan",
  "ac milan": "Milan",
  rossoneri: "Milan",
  lazio: "Lazio",
  roma: "Roma",
  "as roma": "Roma",
  giallorossi: "Roma",
  atalanta: "Atalanta",
  "adl": "De Laurentiis",
  "de laurentiis": "De Laurentiis",
  "aurelio": "De Laurentiis",
  conte: "Conte",
  "antonio conte": "Conte",
  kvara: "Kvaratskhelia",
  "kvaratskhelia": "Kvaratskhelia",
  "lautaro": "Lautaro Martinez",
  "lautaro martinez": "Lautaro Martinez",
  mctominay: "McTominay",
  mctomini: "McTominay",
  "scott mctominay": "McTominay",
  neres: "Neres",
  var: "VAR",
  arbitri: "Arbitri",
  "giovanile napoli": "Napoli",
};

function normalizeKey(s: string): string {
  return s
    .toLowerCase()
    .trim()
    .replace(/\s+/g, " ")
    .replace(/[^\w\s]/g, "");
}

export function normalizeEntity(raw: string): string {
  if (!raw?.trim()) return "";
  const key = normalizeKey(raw);
  const canonical = ALIASES[key];
  if (canonical) return canonical;
  return raw.trim();
}

export function normalizeClaimEntities<T extends { target_entity?: string }>(claim: T): T {
  if (claim.target_entity) {
    return { ...claim, target_entity: normalizeEntity(claim.target_entity) };
  }
  return claim;
}
