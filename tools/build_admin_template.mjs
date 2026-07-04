import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const templatePath = "/private/tmp/ce-seminar-phase1/template.json";
const outputDir =
  "/Users/norihisa/Documents/CE Seminar Finder/outputs/phase1-20260704";
const template = JSON.parse(await fs.readFile(templatePath, "utf8"));

function colLetter(oneBased) {
  let value = oneBased;
  let result = "";
  while (value > 0) {
    value -= 1;
    result = String.fromCharCode(65 + (value % 26)) + result;
    value = Math.floor(value / 26);
  }
  return result;
}

function defaultWidth(header) {
  if (header === "organization_name" || header === "organizer_name") return 38;
  if (header.includes("prefecture")) return 14;
  if (header.includes("url")) return 42;
  if (header.includes("_at") || header.includes("date")) return 23;
  if (header.includes("id")) return 25;
  if (
    header.includes("text") ||
    header.includes("note") ||
    header.includes("summary") ||
    header.includes("reason") ||
    header.includes("condition") ||
    header.includes("message")
  ) {
    return 36;
  }
  if (header.includes("status") || header.includes("type")) return 18;
  return 20;
}

function safeTableName(title) {
  return `${title.replace(/[^A-Za-z0-9]/g, "")}Table`;
}

const workbook = Workbook.create();

for (const spec of template.sheets) {
  workbook.worksheets.add(spec.title);
}

for (const spec of template.sheets) {
  const sheet = workbook.worksheets.getItem(spec.title);
  const headers = spec.headers;
  const headerCount = headers.length;
  const lastColumn = colLetter(headerCount);
  let rows = [];
  if (spec.title === "Sources") rows = template.source_rows;
  if (spec.title === "Settings") rows = template.settings_rows;

  sheet.showGridLines = true;
  sheet.getRange(`A1:${lastColumn}1`).values = [headers];
  if (rows.length > 0) {
    sheet.getRangeByIndexes(1, 0, rows.length, headerCount).values = rows;
  }

  const headerRange = sheet.getRange(`A1:${lastColumn}1`);
  headerRange.format = {
    fill: "#E2E8F0",
    font: { bold: true, color: "#1F2937", size: 10 },
    verticalAlignment: "center",
    horizontalAlignment: "center",
    wrapText: true,
    borders: {
      bottom: { style: "medium", color: "#94A3B8" },
    },
  };
  headerRange.format.rowHeight = 34;
  sheet.freezePanes.freezeRows(1);
  if (spec.frozen_columns > 0) {
    sheet.freezePanes.freezeColumns(spec.frozen_columns);
  }

  const usedRowCount = Math.max(rows.length + 1, 2);
  const usedRange = sheet.getRangeByIndexes(0, 0, usedRowCount, headerCount);
  usedRange.format.font = { name: "Arial", size: 10, color: "#111827" };
  if (usedRowCount > 1) {
    sheet
      .getRangeByIndexes(1, 0, usedRowCount - 1, headerCount)
      .format.verticalAlignment = "top";
  }

  headers.forEach((header, index) => {
    const width = spec.column_widths?.[header]
      ? Math.min(Math.max(spec.column_widths[header] / 7, 12), 55)
      : defaultWidth(header);
    sheet
      .getRangeByIndexes(0, index, usedRowCount, 1)
      .format.columnWidth = width;
  });

  const wrapHeaders = new Set([
    "summary",
    "admin_note",
    "source_excerpt",
    "source_urls",
    "decision_note",
    "notes",
    "text",
    "evidence_text",
    "message",
  ]);
  headers.forEach((header, index) => {
    if (wrapHeaders.has(header)) {
      sheet.getRangeByIndexes(1, index, Math.max(rows.length, 1), 1).format.wrapText =
        true;
    }
  });

  for (const dropdown of spec.dropdowns) {
    const index = headers.indexOf(dropdown.column);
    const destination = `${colLetter(index + 1)}2:${colLetter(index + 1)}500`;
    const formula = dropdown.settings_range.replace(
      "Settings!",
      "'Settings'!",
    );
    sheet.getRange(destination).dataValidation = {
      rule: {
        type: "list",
        formula1: formula,
      },
    };
  }

  const protectedFill = "#F1F5F9";
  for (const header of spec.protected_columns) {
    const index = headers.indexOf(header);
    if (index >= 0) {
      sheet
        .getRangeByIndexes(1, index, 199, 1)
        .format.fill = protectedFill;
    }
  }

  const editableBySheet = {
    Events: [
      "publication_status",
      "review_status",
      "review_label",
      "review_reason_display",
      "duplicate_status",
      "genres",
      "admin_note",
    ],
    ReviewQueue: [
      "assignee",
      "decision",
      "automation_choice",
      "decision_note",
    ],
    Sources: [
      "enabled",
      "auto_publish_policy",
      "request_interval_seconds",
      "max_requests_per_run",
      "contact_url",
      "notes",
    ],
    DuplicateCandidates: ["status", "canonical_event_id", "reviewed_at"],
    AutomationRules: ["enabled", "condition_json", "action", "expires_at", "notes"],
  };
  for (const header of editableBySheet[spec.title] ?? []) {
    const index = headers.indexOf(header);
    if (index >= 0) {
      sheet
        .getRangeByIndexes(1, index, 199, 1)
        .format.fill = "#FEF3C7";
    }
  }

  if (spec.filter_enabled) {
    const tableRows = Math.max(rows.length + 1, 2);
    if (rows.length === 0) {
      sheet.getRangeByIndexes(1, 0, 1, headerCount).values = [
        Array(headerCount).fill(null),
      ];
    }
    const table = sheet.tables.add(
      `A1:${lastColumn}${tableRows}`,
      true,
      safeTableName(spec.title),
    );
    table.style = "TableStyleLight1";
    table.showBandedColumns = false;
    table.showFilterButton = true;
  }

  if (spec.title === "Events") {
    const range = sheet.getRange(`A2:${lastColumn}200`);
    range.conditionalFormats.addCustom('=$C2="公開"', { fill: "#E8F5E9" });
    range.conditionalFormats.addCustom('=$C2="確認待ち"', { fill: "#FFF8E1" });
    range.conditionalFormats.addCustom('=$C2="非公開"', { fill: "#FDECEC" });
    range.conditionalFormats.addCustom('=$C2="アーカイブ"', { fill: "#F3F4F6" });
  }
  if (spec.title === "ReviewQueue") {
    const range = sheet.getRange(`A2:${lastColumn}200`);
    range.conditionalFormats.addCustom('=$C2="緊急"', {
      fill: "#FEE2E2",
      font: { bold: true, color: "#991B1B" },
    });
    range.conditionalFormats.addCustom('=$C2="高"', { fill: "#FFEDD5" });
  }
}

await fs.mkdir(outputDir, { recursive: true });

const overview = await workbook.inspect({
  kind: "sheet",
  include: "id,name",
  maxChars: 8000,
});
console.log(overview.ndjson);

const keyRanges = [
  ["Events", "A1:H6"],
  ["ReviewQueue", "A1:H6"],
  ["Sources", "A1:H12"],
  ["Settings", "A1:E15"],
];
for (const [sheetName, range] of keyRanges) {
  const check = await workbook.inspect({
    kind: "table",
    range: `${sheetName}!${range}`,
    include: "values,formulas",
    tableMaxRows: 15,
    tableMaxCols: 8,
    maxChars: 5000,
  });
  console.log(check.ndjson);
}

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

for (const spec of template.sheets) {
  const previewColumns = Math.min(spec.headers.length, 8);
  const previewRows =
    spec.title === "Sources" ? 11 : spec.title === "Settings" ? 15 : 6;
  const preview = await workbook.render({
    sheetName: spec.title,
    range: `A1:${colLetter(previewColumns)}${previewRows}`,
    scale: 1,
    format: "png",
  });
  const safeName = spec.title.replace(/[^A-Za-z0-9]/g, "_") || spec.title;
  await fs.writeFile(
    `/private/tmp/ce-seminar-phase1/preview-${safeName}.png`,
    new Uint8Array(await preview.arrayBuffer()),
  );
}

const output = await SpreadsheetFile.exportXlsx(workbook);
const outputPath = `${outputDir}/CE_Seminar_Finder_Admin_Template.xlsx`;
await output.save(outputPath);

const exportedBlob = await FileBlob.load(outputPath);
const verifiedWorkbook = await SpreadsheetFile.importXlsx(exportedBlob);
const verifiedSheets = await verifiedWorkbook.inspect({
  kind: "sheet",
  include: "id,name",
  maxChars: 8000,
});
const verifiedSheetLines = verifiedSheets.ndjson
  .split("\n")
  .filter((line) => line.trim().length > 0);
if (verifiedSheetLines.length !== 13) {
  throw new Error(`Expected 13 exported sheets, found ${verifiedSheetLines.length}`);
}
const verifiedErrors = await verifiedWorkbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "exported workbook formula error scan",
});
if (!verifiedErrors.ndjson.includes("matched 0 entries")) {
  throw new Error(`Exported workbook contains formula errors: ${verifiedErrors.ndjson}`);
}
console.log(`verified_sheets=${verifiedSheetLines.length}`);
console.log(outputPath);
