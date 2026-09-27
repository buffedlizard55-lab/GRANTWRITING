/**
 * Quote CSV cells and neutralize spreadsheet formula prefixes.
 *
 * Source fields are public, but their contents are external data. Spreadsheet
 * applications can execute cells beginning with =, +, -, or @; leading
 * whitespace/control characters can be used to obscure those prefixes.
 */
const FORMULA_PREFIX = /^[\u0000-\u0020\uFEFF]*[=+\-@]/u;

export function csvCell(value) {
  const text = value == null ? "" : String(value);
  const safe = FORMULA_PREFIX.test(text) ? `'${text}` : text;
  return `"${safe.replaceAll('"', '""')}"`;
}
