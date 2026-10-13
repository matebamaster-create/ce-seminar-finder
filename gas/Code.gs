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
  if (["公開", "修正後公開", "要確認付き公開"].indexOf(review.decision) >= 0) {
    validatePublishable_(rowObject_(sheet, row));
  }
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

/**
 * Web administration console.
 *
 * Optional Script Properties:
 * - SPREADSHEET_ID: required only for a standalone Apps Script project
 * - ADMIN_EMAILS: comma-separated allowlist
 * - GITHUB_OWNER / GITHUB_REPOSITORY / GITHUB_TOKEN / GITHUB_REF
 */

function doGet() {
  requireAdmin_();
  return HtmlService.createTemplateFromFile("Index")
    .evaluate()
    .setTitle("CE Seminar Finder 管理")
    .addMetaTag("viewport", "width=device-width, initial-scale=1");
}

function getAdminDashboard() {
  requireAdmin_();
  const spreadsheet = adminSpreadsheet_();
  const events = sheetObjects_(requiredSheet_(spreadsheet, "Events"))
    .filter(function (event) {
      return event.event_id;
    })
    .map(adminEvent_);
  const titleById = events.reduce(function (result, event) {
    result[event.event_id] = event.title;
    return result;
  }, {});
  const openReviews = sheetObjects_(requiredSheet_(spreadsheet, "ReviewQueue"))
    .filter(function (review) {
      return (
        review.review_id &&
        (!review.decision || review.decision === "未判断")
      );
    });
  const automaticRule = sheetObjects_(requiredSheet_(spreadsheet, "AutomationRules")).find(function(rule) {
    return rule.rule_id === "rule_grounded_v1_west20261013";
  });
  const processingReviews = openReviews.filter(function(review) {
    return !automaticRule || String(review.reason_codes || "").trim() === "AUTO_PROCESSING_PENDING";
  });
  const reviews = openReviews.filter(function(review) {
      return !!automaticRule && String(review.reason_codes || "").trim() !== "AUTO_PROCESSING_PENDING";
    }).map(function (review) {
      return {
        review_id: review.review_id,
        event_id: review.event_id,
        event_title: titleById[review.event_id] || review.event_id,
        priority: review.priority || "通常",
        reason_codes: review.reason_codes || "",
        suggested_action: review.suggested_action || "",
        source_excerpt: review.source_excerpt || "",
        source_urls: review.source_urls || "",
        uncertain_fields: review.uncertain_fields || "",
        opened_at: review.opened_at || "",
        due_at: review.due_at || "",
        assignee: review.assignee || "",
      };
    });
  const sources = sheetObjects_(requiredSheet_(spreadsheet, "Sources"))
    .filter(function (source) {
      return source.source_id;
    })
    .map(function (source) {
      return {
        source_id: source.source_id,
        organization_name: source.organization_name,
        prefecture: source.prefecture,
        base_url: source.base_url,
        enabled: truthy_(source.enabled),
        last_success_at: source.last_success_at || "",
        consecutive_failures: Number(source.consecutive_failures || 0),
        auto_publish_policy: source.auto_publish_policy || "review_only",
        notes: source.notes || "",
      };
    });
  const logSheet = requiredSheet_(spreadsheet, "FetchLogs");
  const latestSource = {};
  if (logSheet.getLastRow() > 1) {
    const start = Math.max(2, logSheet.getLastRow() - 499);
    logSheet.getRange(start, 1, logSheet.getLastRow() - start + 1, 15).getDisplayValues().forEach(function(row) {
      if (row[3] === "source_summary") latestSource[row[2]] = {status: row[12], message: row[13], at: row[6]};
    });
  }
  sources.forEach(function(source) {
    const last = latestSource[source.source_id];
    const names = {success: "取得成功", partial: "一部取得", failed: "取得失敗", technical_hold: "取得方法の調整が必要", disabled: "停止中"};
    source.last_result = last ? names[last.status] || last.status : "未検証";
    source.last_message = last ? last.message : "";
  });
  events.sort(function (a, b) {
    return String(a.effective_end_at || "9999").localeCompare(
      String(b.effective_end_at || "9999")
    );
  });
  reviews.sort(function (a, b) {
    const order = { 緊急: 0, 高: 1, 通常: 2, 低: 3 };
    const aOrder = Object.prototype.hasOwnProperty.call(order, a.priority)
      ? order[a.priority]
      : 2;
    const bOrder = Object.prototype.hasOwnProperty.call(order, b.priority)
      ? order[b.priority]
      : 2;
    return aOrder - bOrder;
  });
  const github = githubWorkflowConnection_();
  return {
    generated_at: new Date().toISOString(),
    actor: adminActor_(),
    spreadsheet_url: spreadsheet.getUrl(),
    events: events,
    reviews: reviews,
    sources: sources,
    stats: {
      total: events.length,
      published: events.filter(function (event) {
        return event.publication_status === "公開";
      }).length,
      pending: events.filter(function (event) {
        return event.publication_status === "確認待ち";
      }).length,
      review: automaticRule ? reviews.length : null,
      processing: processingReviews.length,
      source_errors: sources.filter(function (source) {
        return source.consecutive_failures > 0;
      }).length,
    },
    automatic_review: {configured: !!automaticRule, enabled: !!automaticRule && truthy_(automaticRule.enabled)},
    connections: {
      github_actions: github.connected,
      github_message: github.message,
    },
    options: {
      publication_statuses: ["公開", "非公開", "確認待ち", "アーカイブ"],
      review_labels: ["なし", "あり"],
      event_types: [
        "セミナー",
        "研修会",
        "講習会",
        "学会・大会",
        "研究会",
        "オンデマンド",
        "その他",
      ],
      genres: [
        "血液浄化",
        "呼吸",
        "循環",
        "医療機器管理",
        "手術室",
        "教育・研究",
        "DX・IT",
        "その他",
      ],
      formats: ["Web", "オンデマンド", "ハイブリッド", "現地開催", "要確認"],
      fee_categories: ["無料", "有料", "要確認"],
      organizer_types: [
        "技士会主催",
        "関連団体主催",
        "企業主催",
        "企業共催",
        "要確認",
      ],
    },
    rollout: rolloutRegions_(),
  };
}

function getAdminExtractionDetails(eventId) {
  requireAdmin_();
  const spreadsheet = adminSpreadsheet_();
  if (!eventId || !findRow_(requiredSheet_(spreadsheet, "Events"), "event_id", eventId)) {
    throw new Error("対象イベントが見つかりません。");
  }
  const allowed = adminEditableFields_().concat(["is_event", "event_date_precision"]);
  return sheetObjects_(requiredSheet_(spreadsheet, "AutoFieldValues"))
    .filter(function (row) { return row.event_id === eventId && allowed.indexOf(row.field_name) >= 0; })
    .slice(0, 100).map(function (row) {
      let value;
      try { value = JSON.parse(row.normalized_value_json || "null"); }
      catch (error) { value = null; }
      let location = {};
      try { location = JSON.parse(row.evidence_location || "{}"); }
      catch (error) { location = {}; }
      if (!location || typeof location !== "object" || Array.isArray(location)) location = {};
      return {field_name: row.field_name, value: value,
        confidence: Math.max(0, Math.min(1, Number(row.confidence) || 0)),
        extractor: row.extractor === "ai" ? "ai" : "rule",
        model: String(row.model || "").slice(0, 100),
        evidence: String(row.evidence_text || "").slice(0, 300),
        pdf_url: /^https?:\/\//i.test(String(location.pdf_url || "")) ? location.pdf_url : "",
        page_from: Number(location.page_from) || 0, page_to: Number(location.page_to) || 0,
        extracted_at: row.extracted_at || ""};
    });
}

function saveAdminEvent(payload) {
  const actor = requireAdmin_();
  if (!payload || !payload.event_id || !payload.values) {
    throw new Error("イベントIDまたは更新内容がありません。");
  }
  const spreadsheet = adminSpreadsheet_();
  const sheet = requiredSheet_(spreadsheet, "Events");
  const row = findRow_(sheet, "event_id", payload.event_id);
  if (!row) {
    throw new Error("対象イベントが見つかりません。");
  }
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const before = rowObject_(sheet, row);
    if (
      payload.expected_updated_at &&
      before.last_admin_updated_at &&
      payload.expected_updated_at !== before.last_admin_updated_at
    ) {
      throw new Error(
        "ほかの管理者が先に更新しました。画面を再読み込みしてください。"
      );
    }
    const allowed = adminEditableFields_();
    const normalized = {};
    Object.keys(payload.values).forEach(function (field) {
      if (allowed.indexOf(field) < 0) {
        throw new Error("管理画面から更新できない項目です: " + field);
      }
      const value = normalizeAdminValue_(field, payload.values[field]);
      validateAdminValue_(field, value);
      normalized[field] = value;
    });
    const proposed = Object.assign({}, before, normalized);
    if (proposed.publication_status === "公開") validatePublishable_(proposed);
    Object.keys(normalized).forEach(function(field) {
      const value = normalized[field];
      setCellByHeader_(sheet, row, field, value);
      if (String(before[field] || "") !== String(value)) {
        appendByHeaders_(requiredSheet_(spreadsheet, "FieldOverrides"), {
          override_id: "ovr_" + Utilities.getUuid().replace(/-/g, ""),
          event_id: payload.event_id,
          field_name: field,
          override_value_json: JSON.stringify(value),
          active: true,
          reason: "管理画面で修正",
          updated_by: actor,
          updated_at: new Date().toISOString(),
        });
      }
    });
    const actedAt = new Date().toISOString();
    setCellByHeader_(sheet, row, "last_admin_updated_at", actedAt);
    const after = rowObject_(sheet, row);
    appendByHeaders_(requiredSheet_(spreadsheet, "ReviewActions"), {
      action_id: "act_" + Utilities.getUuid().replace(/-/g, ""),
      review_id: "",
      event_id: payload.event_id,
      action: "admin_edit",
      before_json: JSON.stringify(before),
      after_json: JSON.stringify(after),
      automation_choice: "次回も確認",
      actor: actor,
      acted_at: actedAt,
      note: String(payload.note || "管理画面から更新"),
    });
    SpreadsheetApp.flush();
    return {
      ok: true,
      message: "イベントを更新しました。",
      event: adminEvent_(after),
    };
  } finally {
    lock.releaseLock();
  }
}

function decideReviewFromAdmin(payload) {
  const actor = requireAdmin_();
  if (!payload || !payload.review_id || !payload.decision) {
    throw new Error("確認IDまたは判断内容がありません。");
  }
  if (
    ["公開", "要確認付き公開", "非公開"].indexOf(payload.decision) < 0
  ) {
    throw new Error("管理画面で選択できない判断です。");
  }
  const spreadsheet = adminSpreadsheet_();
  const reviewSheet = requiredSheet_(spreadsheet, "ReviewQueue");
  const reviewRow = findRow_(reviewSheet, "review_id", payload.review_id);
  if (!reviewRow) {
    throw new Error("要確認項目が見つかりません。");
  }
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const review = rowObject_(reviewSheet, reviewRow);
    if (review.decision && review.decision !== "未判断") {
      throw new Error("この項目はすでに判断済みです。");
    }
    review.decision = payload.decision;
    review.decision_note = String(payload.note || "");
    review.automation_choice = "次回も確認";
    const eventsSheet = requiredSheet_(spreadsheet, "Events");
    const eventRow = findRow_(eventsSheet, "event_id", review.event_id);
    if (!eventRow) {
      throw new Error("対象イベントが見つかりません。");
    }
    const before = rowObject_(eventsSheet, eventRow);
    applyDecisionToEvent_(eventsSheet, eventRow, review);
    const actedAt = new Date().toISOString();
    const after = rowObject_(eventsSheet, eventRow);
    setCellByHeader_(reviewSheet, reviewRow, "decision", payload.decision);
    setCellByHeader_(
      reviewSheet,
      reviewRow,
      "decision_note",
      review.decision_note
    );
    setCellByHeader_(reviewSheet, reviewRow, "decided_at", actedAt);
    appendByHeaders_(requiredSheet_(spreadsheet, "ReviewActions"), {
      action_id: "act_" + Utilities.getUuid().replace(/-/g, ""),
      review_id: review.review_id,
      event_id: review.event_id,
      action: actionCode_(payload.decision),
      before_json: JSON.stringify(before),
      after_json: JSON.stringify(after),
      automation_choice: "次回も確認",
      actor: actor,
      acted_at: actedAt,
      note: review.decision_note,
    });
    SpreadsheetApp.flush();
    return { ok: true, message: "判断を確定しました。" };
  } finally {
    lock.releaseLock();
  }
}

function setSourceEnabledFromAdmin(sourceId, enabled) {
  const actor = requireAdmin_();
  const spreadsheet = adminSpreadsheet_();
  const sheet = requiredSheet_(spreadsheet, "Sources");
  const row = findRow_(sheet, "source_id", sourceId);
  if (!row) throw new Error("取得元が見つかりません。");
  const value = enabled === true;
  setCellByHeader_(sheet, row, "enabled", value);
  appendByHeaders_(requiredSheet_(spreadsheet, "ReviewActions"), {
    action_id: "act_" + Utilities.getUuid().replace(/-/g, ""), event_id: "",
    action: value ? "source_enable" : "source_disable", actor: actor,
    acted_at: new Date().toISOString(), note: sourceId,
  });
  return {ok: true, message: value ? "日次取得を有効にしました。" : "日次取得を停止しました。"};
}

function setAutomaticReviewEnabledFromAdmin(enabled) {
  const actor = requireAdmin_();
  if (typeof enabled !== "boolean") throw new Error("自動公開の設定が不正です。");
  const spreadsheet = adminSpreadsheet_();
  const sheet = requiredSheet_(spreadsheet, "AutomationRules");
  const row = findRow_(sheet, "rule_id", "rule_grounded_v1_west20261013");
  if (!row) throw new Error("自動整理の初期設定は一括処理の終了後に反映されます。");
  setCellByHeader_(sheet, row, "enabled", enabled);
  appendByHeaders_(requiredSheet_(spreadsheet, "ReviewActions"), {
    action_id: "act_" + Utilities.getUuid().replace(/-/g, ""), event_id: "",
    action: enabled ? "auto_review_enable" : "auto_review_disable", actor: actor,
    acted_at: new Date().toISOString(), note: "承認済みの公式原文照合ルールだけを切り替え",
  });
  return {ok: true, message: enabled ? "条件付き自動公開を再開しました。" : "条件付き自動公開を停止しました。"};
}

function requestSourceUpdateFromAdmin(sourceId) {
  requireAdmin_();
  const spreadsheet = adminSpreadsheet_();
  const sheet = requiredSheet_(spreadsheet, "Sources");
  const row = findRow_(sheet, "source_id", sourceId);
  if (!row) {
    throw new Error("取得元が見つかりません。");
  }
  dispatchDailyWorkflow_(sourceId, false);
  return { ok: true, message: sourceId + " の取得を依頼しました。" };
}

function publishAdminSite() {
  requireAdmin_();
  dispatchDailyWorkflow_("", true);
  return {
    ok: true,
    message: "公開ページの更新を依頼しました。通常1〜3分で反映されます。",
  };
}

function githubWorkflowConnection_() {
  const properties = PropertiesService.getScriptProperties();
  const owner = properties.getProperty("GITHUB_OWNER");
  const repository = properties.getProperty("GITHUB_REPOSITORY");
  const token = properties.getProperty("GITHUB_TOKEN");
  if (!owner || !repository || !token) {
    return {connected: false, message: "GitHub公開更新の接続設定がありません。"};
  }
  try {
    const response = UrlFetchApp.fetch(
      "https://api.github.com/repos/" + encodeURIComponent(owner) + "/" +
      encodeURIComponent(repository) + "/actions/workflows/daily.yml", {
        headers: {Accept: "application/vnd.github+json", Authorization: "Bearer " + token,
          "X-GitHub-Api-Version": "2022-11-28"},
        muteHttpExceptions: true,
      });
    const status = response.getResponseCode();
    if (status === 200) return {connected: true, message: "GitHub接続確認済み。起動権限は更新実行時に確認します。"};
    return {connected: false, message: status === 401
      ? "GitHub接続の認証期限切れ、または無効な認証情報です。接続の更新が必要です。"
      : "GitHub接続を確認できません（HTTP " + status + "）。権限・接続先を確認してください。"};
  } catch (error) {
    // Do not return fetch error details or credentials to the browser.
    return {connected: false, message: "GitHubへの接続を確認できませんでした。時間をおいて再読み込みしてください。"};
  }
}

function updateGithubConnectionFromAdmin(tokenInput) {
  const actor = requireAdmin_();
  const ownerEmail = Session.getEffectiveUser().getEmail();
  if (!ownerEmail || actor.toLowerCase() !== ownerEmail.toLowerCase()) {
    throw new Error("認証の更新は、この管理画面の所有者だけが行えます。");
  }
  const token = typeof tokenInput === "string" ? tokenInput.trim() : "";
  if (!/^github_pat_[A-Za-z0-9_]{20,240}$/.test(token)) {
    throw new Error("GitHubで再発行した、権限を限定したトークンを入力してください。");
  }
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) throw new Error("処理中です。少し待ってから再試行してください。");
  try {
    // Validate actual Actions write access before replacing the stored credential.
    // Only this project's existing workflow is dispatched; the destination is not editable.
    dispatchDailyWorkflow_("", true, token);
    PropertiesService.getScriptProperties().setProperty("GITHUB_TOKEN", token);
    let auditSaved = true;
    try {
      const spreadsheet = adminSpreadsheet_();
      appendByHeaders_(requiredSheet_(spreadsheet, "ReviewActions"), {
        action_id: "act_" + Utilities.getUuid().replace(/-/g, ""), event_id: "",
        action: "github_connection_update", actor: actor, acted_at: new Date().toISOString(),
        note: "既存の公開更新処理への接続を更新。認証情報は履歴に保存しません。",
      });
    } catch (error) {
      auditSaved = false;
    }
    return {ok: true, message: "GitHub接続を更新し、公開ページの更新を起動しました。" +
      (auditSaved ? "" : " 接続は保存済みですが、操作履歴の記録に失敗しました。")};
  } finally {
    lock.releaseLock();
  }
}

function dispatchDailyWorkflow_(sourceIds, publish, tokenOverride) {
  const properties = PropertiesService.getScriptProperties();
  const owner = properties.getProperty("GITHUB_OWNER");
  const repository = properties.getProperty("GITHUB_REPOSITORY");
  const token = tokenOverride || properties.getProperty("GITHUB_TOKEN");
  const ref = properties.getProperty("GITHUB_REF") || "main";
  if (!owner || !repository || !token) {
    throw new Error(
      "公開更新の接続設定がありません。Script PropertiesのGitHub設定を確認してください。"
    );
  }
  const endpoint =
    "https://api.github.com/repos/" +
    encodeURIComponent(owner) +
    "/" +
    encodeURIComponent(repository) +
    "/actions/workflows/daily.yml/dispatches";
  let response;
  try {
    response = UrlFetchApp.fetch(endpoint, {
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
          source_ids: String(sourceIds || ""),
          publish: publish ? "true" : "false",
          sync_current_events: "false",
        },
      }),
      muteHttpExceptions: true,
    });
  } catch (error) {
    // Never expose request headers, response bodies, or submitted credentials.
    throw new Error("GitHubへ接続できませんでした。認証は変更していません。");
  }
  if (response.getResponseCode() !== 204) {
    throw new Error(
      "GitHub Actionsを起動できませんでした（HTTP " +
        response.getResponseCode() +
        "）。"
    );
  }
}

function adminSpreadsheet_() {
  const id = PropertiesService.getScriptProperties().getProperty(
    "SPREADSHEET_ID"
  );
  if (id) {
    return SpreadsheetApp.openById(id);
  }
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  if (!spreadsheet) {
    throw new Error("管理スプレッドシートへ接続できません。");
  }
  return spreadsheet;
}

function requireAdmin_() {
  const actor = adminActor_();
  const configured = PropertiesService.getScriptProperties().getProperty(
    "ADMIN_EMAILS"
  );
  const allowed = String(configured || "")
    .split(",")
    .map(function (email) {
      return email.trim().toLowerCase();
    })
    .filter(String);
  if (allowed.length && allowed.indexOf(actor.toLowerCase()) < 0) {
    throw new Error("この管理画面を利用する権限がありません。");
  }
  return actor;
}

function adminActor_() {
  return (
    Session.getActiveUser().getEmail() ||
    Session.getEffectiveUser().getEmail() ||
    "apps-script-admin"
  );
}

function sheetObjects_(sheet) {
  if (sheet.getLastRow() < 2) {
    return [];
  }
  const headers = headers_(sheet);
  return sheet
    .getRange(2, 1, sheet.getLastRow() - 1, headers.length)
    .getDisplayValues()
    .map(function (values) {
      return headers.reduce(function (result, header, index) {
        result[header] = values[index];
        return result;
      }, {});
    });
}

function adminEvent_(event) {
  const result = {};
  [
    "event_id",
    "publication_status",
    "review_status",
    "review_label",
    "review_reason_codes",
    "review_reason_display",
    "duplicate_status",
    "data_quality_score",
    "title",
    "summary",
    "event_type",
    "genres",
    "detailed_tags",
    "organizer_name",
    "organizer_type",
    "source_prefecture",
    "venue_prefecture",
    "venue_name",
    "venue_address",
    "format",
    "audience_conditions",
    "capacity_text",
    "credits_text",
    "event_start_at",
    "event_end_at",
    "event_date_precision",
    "stream_start_at",
    "stream_end_at",
    "stream_period_text",
    "application_deadline_at",
    "application_deadline_text",
    "effective_end_at",
    "fee_category",
    "fee_text",
    "fee_verified",
    "primary_official_url",
    "application_url",
    "primary_pdf_url",
    "last_auto_fetched_at",
    "last_admin_updated_at",
    "last_verified_at",
    "admin_note",
  ].forEach(function (field) {
    result[field] = event[field] || "";
  });
  result.auto_publish_eligible = truthy_(event.auto_publish_eligible);
  return result;
}

function adminEditableFields_() {
  return [
    "publication_status",
    "review_status",
    "review_label",
    "review_reason_display",
    "title",
    "summary",
    "event_type",
    "genres",
    "detailed_tags",
    "organizer_name",
    "organizer_type",
    "source_prefecture",
    "venue_prefecture",
    "venue_name",
    "venue_address",
    "format",
    "audience_conditions",
    "capacity_text",
    "credits_text",
    "event_start_at",
    "event_end_at",
    "event_date_precision",
    "stream_start_at",
    "stream_end_at",
    "stream_period_text",
    "application_deadline_at",
    "application_deadline_text",
    "effective_end_at",
    "fee_category",
    "fee_text",
    "fee_verified",
    "primary_official_url",
    "application_url",
    "primary_pdf_url",
    "last_verified_at",
    "admin_note",
  ];
}

function normalizeAdminValue_(field, value) {
  if (field === "genres" || field === "detailed_tags") {
    return String(value || "")
      .split(/\n|,/)
      .map(function (item) {
        return item.trim();
      })
      .filter(String)
      .join("\n");
  }
  if (field === "fee_verified") {
    return truthy_(value);
  }
  return String(value == null ? "" : value).trim();
}

function validateAdminValue_(field, value) {
  const allowed = {
    publication_status: ["公開", "非公開", "確認待ち", "アーカイブ"],
    review_status: ["未確認", "確認済み", "要修正"],
    review_label: ["なし", "あり"],
    event_type: [
      "セミナー",
      "研修会",
      "講習会",
      "学会・大会",
      "研究会",
      "オンデマンド",
      "その他",
    ],
    organizer_type: [
      "技士会主催",
      "関連団体主催",
      "企業主催",
      "企業共催",
      "要確認",
    ],
    format: ["Web", "オンデマンド", "ハイブリッド", "現地開催", "要確認"],
    fee_category: ["無料", "有料", "要確認"],
    event_date_precision: ["", "date", "datetime"],
  };
  if (allowed[field] && allowed[field].indexOf(value) < 0) {
    throw new Error(field + "の選択値が不正です。");
  }
  if (
    ["primary_official_url", "application_url", "primary_pdf_url"].indexOf(
      field
    ) >= 0 &&
    value &&
    !/^https?:\/\//i.test(value)
  ) {
    throw new Error(field + "はhttpまたはhttpsのURLを入力してください。");
  }
  if (/_(?:at)$/.test(field) && value && !/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value)) {
    throw new Error("日時はタイムゾーン付きで入力してください（例：2026-10-20T19:00:00+09:00）。");
  }
}

function validatePublishable_(event) {
  const missing = [];
  if (!event.title) missing.push("イベント名");
  if (!event.organizer_name) missing.push("主催者");
  if (!event.primary_official_url || !/^https?:\/\//i.test(event.primary_official_url)) missing.push("公式URL");
  if (!event.event_start_at && !event.stream_start_at) missing.push("開催日または配信開始日");
  if (missing.length) throw new Error("公開には次の項目が必要です：" + missing.join("、"));
}

function truthy_(value) {
  return value === true || String(value).toUpperCase() === "TRUE";
}

function rolloutRegions_() {
  return [
    {
      name: "九州・沖縄",
      status: "運用中",
      prefectures: "福岡・佐賀・長崎・熊本・大分・宮崎・鹿児島・沖縄",
    },
    {
      name: "中四国",
      status: "実装済み・検証中",
      prefectures: "鳥取・島根・岡山・広島・山口・徳島・香川・愛媛・高知",
    },
    {
      name: "関西",
      status: "実装済み・検証中",
      prefectures: "滋賀・京都・大阪・兵庫・奈良・和歌山",
    },
    {
      name: "東海・北陸",
      status: "実装済み・検証中",
      prefectures: "岐阜・静岡・愛知・三重・富山・石川・福井",
    },
    {
      name: "甲信越・関東",
      status: "予定",
      prefectures: "新潟・山梨・長野・茨城・栃木・群馬・埼玉・千葉・東京・神奈川",
    },
    {
      name: "東北・北海道",
      status: "予定",
      prefectures: "青森・岩手・宮城・秋田・山形・福島・北海道",
    },
  ];
}
