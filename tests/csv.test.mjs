import test from "node:test";
import assert from "node:assert/strict";
import { csvCell } from "../docs/js/csv.js";

test("CSV cells quote delimiters, quotes, and newlines", () => {
  assert.equal(csvCell('A, "quoted" title\nSecond line'), '"A, ""quoted"" title\nSecond line"');
});

test("CSV cells neutralize spreadsheet formulas, including obscured prefixes", () => {
  for (const value of ["=1+1", "+SUM(A1:A2)", "-1+1", "@SUM(A1)", "  =1+1", "\t=1+1", "\uFEFF=1+1"]) {
    assert.equal(csvCell(value), `"'${value}"`);
  }
});

test("ordinary text, empty fields, and numeric values are preserved", () => {
  assert.equal(csvCell("NSF-26-100"), '"NSF-26-100"');
  assert.equal(csvCell(250000), '"250000"');
  assert.equal(csvCell(null), '""');
});
