/**
 * CE Seminar Finder - ReviewQueue administration helper.
 *
 * Bind this project to the private administration spreadsheet.
 * ReviewActions is append-only. AutomationRules is created only after
 * an explicit automation choice and a second confirmation.
 */

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("CE Seminar Finder")
    .addItem("選択したReviewQueueの判断を確定", "finalizeSelectedReview")
    .addItem("選択したSourceを手動取得", "requestSelectedSourceUpdate")
    .addSeparator()
    .addItem("設定とシート構造を確認", "validateAdminWorkbook")
    .addToUi();
}

function requestSelectedSourceUpdate() {
  const ui = SpreadsheetApp.getUi();
  const sheet = SpreadsheetApp.getActiveSheet();
  const row = sheet.getActiveRange().getRow();
  if (sheet.getName() !== "Sources" || row < 2) {
    ui.alert("Sourcesの対象行を選択してください。");
    return;
  }
  const source = rowObject_(sheet, row);
  if (!source.source_id) {
    throw new Error("source_idがありません。");
  }
  const properties = PropertiesService.getScriptProperties();
  const owner = properties.getProperty("GITHUB_OWNER");
  const repository = properties.getProperty("GITHUB_REPOSITORY");
  const token = properties.getProperty("GITHUB_TOKEN");
  const ref = properties.getProperty("GITHUB_REF") || "main";
  if (!owner || !repository || !token) {
    ui.alert(
      "Script PropertiesにGITHUB_OWNER、GITHUB_REPOSITORY、GITHUB_TOKENを設定してください。"
    );
    return;
  }
  const endpoint =
    "https://api.github.com/repos/" +
    encodeURIComponent(owner) +
    "/" +
    encodeURIComponent(repository) +
    "/actions/workflows/daily.yml/dispatches";
  const response = UrlFetchApp.fetch(endpoint, {
    method: "post",
    contentType: "application/json",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: "Bearer " + token,
      "X-GitHub-Api-Version": "2022-11-28",
    },
    payload: JSON.stringify({
      ref: ref,
      inputs: {
        source_ids: source.source_id,
        publish: "false",
      },
    }),
    muteHttpExceptions: true,
  });
  if (response.getResponseCode() !== 204) {
    ui.alert(
      "手動取得を依頼できませんでした。GitHub設定と権限を確認してください（HTTP " +
        response.getResponseCode() +
        "）。"
    );
    return;
  }
  ui.alert(source.source_id + " の手動取得を依頼しました。");
}

function finalizeSelectedReview() {
  const ui = SpreadsheetApp.getUi();
  const spreadsheet = SpreadsheetApp.getActive();
  const activeSheet = spreadsheet.getActiveSheet();
  const activeRow = activeSheet.getActiveRange().getRow();
  if (activeSheet.getName() !== "ReviewQueue" || activeRow < 2) {
    ui.alert("ReviewQueueの対象行を選択してください。");
    return;
  }

  const lock = LockService.getDocumentLock();
  lock.waitLock(30000);
  try {
    const review = rowObject_(activeSheet, activeRow);
    if (!review.review_id || !review.event_id) {
      throw new Error("review_idまたはevent_idがありません。");
    }
    if (!review.decision || review.decision === "未判断") {
      throw new Error("decisionを選択してください。");
    }

    const eventsSheet = requiredSheet_(spreadsheet, "Events");
    const eventRow = findRow_(eventsSheet, "event_id", review.event_id);
    if (!eventRow) {
      throw new Error("Eventsに対象event_idがありません。");
    }
    const before = rowObject_(eventsSheet, eventRow);
    applyDecisionToEvent_(eventsSheet, eventRow, review);
    const after = rowObject_(eventsSheet, eventRow);

    const actedAt = new Date().toISOString();
    const actor = Session.getEffectiveUser().getEmail() || "spreadsheet-admin";
    const actionId = "act_" + Utilities.getUuid().replace(/-/g, "");
    appendByHeaders_(requiredSheet_(spreadsheet, "ReviewActions"), {
      action_id: actionId,
      review_id: review.review_id,
      event_id: review.event_id,
      action: actionCode_(review.decision),
      before_json: JSON.stringify(before),
      after_json: JSON.stringify(after),
      automation_choice: review.automation_choice || "次回も確認",
      actor: actor,
      acted_at: actedAt,
      note: review.decision_note || "",
    });

    setCellByHeader_(activeSheet, activeRow, "decided_at", actedAt);
    maybeCreateAutomationRule_(
      spreadsheet,
      review,
      actionId,
      actor,
      actedAt,
      ui
    );
    SpreadsheetApp.flush();
    ui.alert("判断を確定し、ReviewActionsへ記録しました。");
  } catch (error) {
    ui.alert("判断を確定できませんでした: " + error.message);
    throw error;
  } finally {
    lock.releaseLock();
  }
}

function applyDecisionToEvent_(sheet, row, review) {
  setCellByHeader_(sheet, row, "review_status", "確認済み");
  setCellByHeader_(sheet, row, "last_admin_updated_at", new Date().toISOString());

  if (review.decision === "公開" || review.decision === "修正後公開") {
    setCellByHeader_(sheet, row, "publication_status", "公開");
    setCellByHeader_(sheet, row, "review_label", "なし");
    return;
  }
  if (review.decision === "要確認付き公開") {
    setCellByHeader_(sheet, row, "publication_status", "公開");
    setCellByHeader_(sheet, row, "review_label", "あり");
    return;
  }
  if (review.decision === "非公開") {
    setCellByHeader_(sheet, row, "publication_status", "非公開");
    setCellByHeader_(sheet, row, "review_label", "なし");
    return;
  }
  if (review.decision === "重複統合") {
    const canonical = canonicalIdFromNote_(review.decision_note || "");
    if (!canonical) {
      throw new Error(
        "重複統合ではdecision_noteに canonical_event_id=evt_xxx を記載してください。"
      );
    }
    setCellByHeader_(sheet, row, "publication_status", "非公開");
    setCellByHeader_(sheet, row, "duplicate_status", "統合済み");
    setCellByHeader_(sheet, row, "canonical_event_id", canonical);
    return;
  }
  throw new Error("未対応のdecisionです: " + review.decision);
}

function maybeCreateAutomationRule_(
  spreadsheet,
  review,
  actionId,
  actor,
  actedAt,
  ui
) {
  const choice = review.automation_choice || "次回も確認";
  if (choice === "次回も確認") {
    return;
  }
  if (["自動公開", "要確認付き公開", "非公開"].indexOf(choice) < 0) {
    throw new Error("未対応のautomation_choiceです: " + choice);
  }
  const response = ui.alert(
    "自動化ルールの明示承認",
    "同じ掲載元の次回候補へ「" + choice + "」を適用するルールを作成しますか？",
    ui.ButtonSet.YES_NO
  );
  if (response !== ui.Button.YES) {
    return;
  }

  const sourceId = sourceIdForEvent_(spreadsheet, review.event_id);
  if (!sourceId) {
    throw new Error("EventSourcesからsource_idを特定できないためルールを作成しません。");
  }
  appendByHeaders_(requiredSheet_(spreadsheet, "AutomationRules"), {
    rule_id: "rule_" + Utilities.getUuid().replace(/-/g, ""),
    enabled: true,
    scope: "source",
    condition_json: JSON.stringify({ source_id: sourceId }),
    action: automationAction_(choice),
    approved_from_action_id: actionId,
    approved_by: actor,
    approved_at: actedAt,
    expires_at: "",
    notes: "ReviewQueue " + review.review_id + " から明示承認",
  });
}

function validateAdminWorkbook() {
  const required = [
    "Events",
    "ReviewQueue",
    "EventSources",
    "ReviewActions",
    "AutomationRules",
  ];
  const spreadsheet = SpreadsheetApp.getActive();
  const missing = required.filter(function (name) {
    return !spreadsheet.getSheetByName(name);
  });
  SpreadsheetApp.getUi().alert(
    missing.length
      ? "不足シート: " + missing.join(", ")
      : "必要な管理シートを確認しました。"
  );
}

function sourceIdForEvent_(spreadsheet, eventId) {
  const sheet = requiredSheet_(spreadsheet, "EventSources");
  const row = findRow_(sheet, "event_id", eventId);
  return row ? rowObject_(sheet, row).source_id : "";
}

function canonicalIdFromNote_(note) {
  const match = String(note).match(/canonical_event_id\s*=\s*(evt_[A-Za-z0-9_-]+)/);
  return match ? match[1] : "";
}

function actionCode_(decision) {
  return {
    公開: "publish",
    要確認付き公開: "publish_with_warning",
    修正後公開: "edit",
    非公開: "reject",
    重複統合: "merge",
  }[decision];
}

function automationAction_(choice) {
  return {
    自動公開: "publish",
    要確認付き公開: "publish_with_warning",
    非公開: "reject",
  }[choice];
}

function requiredSheet_(spreadsheet, name) {
  const sheet = spreadsheet.getSheetByName(name);
  if (!sheet) {
    throw new Error("必要なシートがありません: " + name);
  }
  return sheet;
}

function headers_(sheet) {
  return sheet
    .getRange(1, 1, 1, sheet.getLastColumn())
    .getDisplayValues()[0];
}

function rowObject_(sheet, row) {
  const headers = headers_(sheet);
  const values = sheet
    .getRange(row, 1, 1, headers.length)
    .getDisplayValues()[0];
  return headers.reduce(function (result, header, index) {
    result[header] = values[index];
    return result;
  }, {});
}

function setCellByHeader_(sheet, row, header, value) {
  const column = headers_(sheet).indexOf(header) + 1;
  if (!column) {
    throw new Error(sheet.getName() + "に列がありません: " + header);
  }
  sheet.getRange(row, column).setValue(value);
}

function findRow_(sheet, header, value) {
  const column = headers_(sheet).indexOf(header) + 1;
  if (!column || sheet.getLastRow() < 2) {
    return 0;
  }
  const finder = sheet
    .getRange(2, column, sheet.getLastRow() - 1, 1)
    .createTextFinder(String(value))
    .matchEntireCell(true)
    .findNext();
  return finder ? finder.getRow() : 0;
}

function appendByHeaders_(sheet, valueByHeader) {
  const headers = headers_(sheet);
  const row = headers.map(function (header) {
    return Object.prototype.hasOwnProperty.call(valueByHeader, header)
      ? valueByHeader[header]
      : "";
  });
  sheet.appendRow(row);
}
