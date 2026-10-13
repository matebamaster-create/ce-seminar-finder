from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GasAdminTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JavaScript behavior checks")
    def test_processing_is_not_counted_as_human_review_and_policy_toggle_is_admin_only(self):
        script = r'''
const fs = require("node:fs"), vm = require("node:vm"), assert = require("node:assert/strict");
const data = {Events: [{event_id:"evt_one",publication_status:"確認待ち",title:"呼吸セミナー"}],
  ReviewQueue:[{review_id:"one",event_id:"evt_one",decision:"未判断",reason_codes:"AUTO_PROCESSING_PENDING"},
  {review_id:"two",event_id:"evt_one",decision:"未判断",reason_codes:"DATE_CONFLICT"}],
  Sources:[],AutomationRules:[]};
const writes=[], audit=[];
const app=vm.createContext({Utilities:{getUuid:()=>"test-id"}});
vm.runInContext(fs.readFileSync("gas/Code.gs","utf8"),app);
app.requireAdmin_=()=>"owner"; app.adminActor_=()=>"owner";
app.adminSpreadsheet_=()=>({getUrl:()=>"https://docs.google.com/spreadsheets/d/test"});
app.requiredSheet_=(s,n)=>({name:n,getLastRow:()=>1});
app.sheetObjects_=sheet=>data[sheet.name]||[];
app.githubWorkflowConnection_=()=>({connected:true,message:"connected"});
let result=app.getAdminDashboard();
assert.equal(result.stats.processing,2); assert.equal(result.stats.review,null);
assert.equal(result.reviews.length,0); assert.equal(result.automatic_review.configured,false);
data.AutomationRules=[{rule_id:"rule_grounded_v1_west20261013",enabled:true}];
result=app.getAdminDashboard();
assert.equal(result.stats.processing,1); assert.equal(result.stats.review,1);
assert.equal(result.reviews[0].reason_codes,"DATE_CONFLICT");
app.findRow_=()=>2; app.setCellByHeader_=(...args)=>writes.push(args);
app.appendByHeaders_=(s,row)=>audit.push(row);
app.requireAdmin_=()=>{throw Error("denied")};
assert.throws(()=>app.setAutomaticReviewEnabledFromAdmin(false),/denied/); assert.equal(writes.length,0);
app.requireAdmin_=()=>"owner";
assert.throws(()=>app.setAutomaticReviewEnabledFromAdmin("false"),/不正/);
app.setAutomaticReviewEnabledFromAdmin(false); assert.equal(writes[0][3],false);
assert.equal(audit[0].action,"auto_review_disable");
app.findRow_=()=>null; assert.throws(()=>app.setAutomaticReviewEnabledFromAdmin(true),/初期設定/);
'''
        subprocess.run([shutil.which("node"), "-e", script], cwd=ROOT, check=True, capture_output=True, text=True)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JavaScript behavior checks")
    def test_extraction_details_are_admin_only_and_filter_other_events_and_columns(self):
        script = r'''
const fs = require("node:fs"), vm = require("node:vm"), assert = require("node:assert/strict");
const app = vm.createContext({});
vm.runInContext(fs.readFileSync("gas/Code.gs", "utf8"), app);
app.requireAdmin_ = () => {throw Error("denied")};
assert.throws(() => app.getAdminExtractionDetails("one"), /denied/);
app.requireAdmin_ = () => "owner";
app.adminSpreadsheet_ = () => ({}); app.requiredSheet_ = (s,n) => n; app.findRow_ = () => 2;
app.sheetObjects_ = () => [
  {event_id:"one",field_name:"fee_text",normalized_value_json:'"500円"',confidence:".9",extractor:"ai",model:"test",evidence_text:"参加費500円",secret:"must-not-return"},
  {event_id:"other",field_name:"fee_text",normalized_value_json:'"private-other"'},
  {event_id:"one",field_name:"unknown",normalized_value_json:'"private-field"'}
];
const result = app.getAdminExtractionDetails("one");
assert.equal(result.length, 1); assert.equal(result[0].value, "500円"); assert.equal(result[0].confidence, .9);
assert.doesNotMatch(JSON.stringify(result), /must-not-return|private-other|private-field/);
app.findRow_ = () => null; assert.throws(() => app.getAdminExtractionDetails("missing"), /見つかりません/);
app.validateAdminValue_("event_date_precision", "date");
assert.throws(() => app.validateAdminValue_("event_date_precision", "guess"), /不正/);
'''
        subprocess.run([shutil.which("node"), "-e", script], cwd=ROOT, check=True, capture_output=True, text=True)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JavaScript behavior checks")
    def test_secret_rotation_requires_owner_and_dispatch_without_disclosing_secret(self) -> None:
        script = r'''
const fs = require("node:fs"), vm = require("node:vm"), assert = require("node:assert/strict");
const token = "github_pat_" + "a".repeat(40);
const stored = {GITHUB_OWNER: "owner", GITHUB_REPOSITORY: "repo", GITHUB_TOKEN: "previous", GITHUB_REF: "main"};
let status = 403, actor = "owner@example.test", released = 0;
const requests = [], audit = [];
const app = vm.createContext({
  PropertiesService: {getScriptProperties: () => ({getProperty: n => stored[n], setProperty: (n,v) => {stored[n] = v}})},
  Session: {getEffectiveUser: () => ({getEmail: () => "owner@example.test"})},
  LockService: {getScriptLock: () => ({tryLock: () => true, releaseLock: () => released++})},
  UrlFetchApp: {fetch: (url, options) => {requests.push({url, options}); return {getResponseCode: () => status}}},
  Utilities: {getUuid: () => "test-id"},
});
vm.runInContext(fs.readFileSync("gas/Code.gs", "utf8"), app);
app.requireAdmin_ = () => actor;
app.adminSpreadsheet_ = () => ({});
app.requiredSheet_ = () => ({});
app.appendByHeaders_ = (sheet, row) => audit.push(row);
assert.throws(() => app.updateGithubConnectionFromAdmin("bad"), /トークン/);
assert.equal(requests.length, 0);
assert.throws(() => app.updateGithubConnectionFromAdmin(token), /403/);
assert.equal(stored.GITHUB_TOKEN, "previous");
assert.equal(audit.length, 0);
status = 204;
const result = app.updateGithubConnectionFromAdmin(token);
assert.equal(stored.GITHUB_TOKEN, token);
assert.equal(result.ok, true);
assert.equal(requests.at(-1).url, "https://api.github.com/repos/owner/repo/actions/workflows/daily.yml/dispatches");
assert.equal(JSON.parse(requests.at(-1).options.payload).inputs.publish, "true");
assert.doesNotMatch(JSON.stringify(result) + JSON.stringify(audit), new RegExp(token));
actor = "other@example.test";
const count = requests.length;
assert.throws(() => app.updateGithubConnectionFromAdmin(token), /所有者/);
assert.equal(requests.length, count);
actor = "owner@example.test";
app.UrlFetchApp.fetch = () => {throw Error(token)};
assert.throws(() => app.updateGithubConnectionFromAdmin(token), error => !error.message.includes(token));
assert.equal(released, 3);
'''
        subprocess.run([shutil.which("node"), "-e", script], cwd=ROOT, check=True, capture_output=True, text=True)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JavaScript behavior checks")
    def test_secret_form_clears_cancelled_input_and_rejects_empty_save(self) -> None:
        script = r'''
const fs = require("node:fs"), vm = require("node:vm"), assert = require("node:assert/strict");
const elements = new Map();
const document = {querySelectorAll: () => [], getElementById: id => {
  if (!elements.has(id)) elements.set(id, {value: "", hidden: true, addEventListener: () => {}, focus: () => {}});
  return elements.get(id);
}};
const ui = vm.createContext({document});
const html = fs.readFileSync("gas/Index.html", "utf8");
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1].replace(/\n    loadData\(\);/, ""), ui);
const messages = []; ui.showToast = message => messages.push(message);
ui.openConnection();
assert.equal(document.getElementById("connection-modal").hidden, false);
document.getElementById("github-token").value = "test-secret";
ui.closeConnection();
assert.equal(document.getElementById("github-token").value, "");
assert.equal(document.getElementById("connection-modal").hidden, true);
ui.saveConnection();
assert.match(messages.at(-1), /入力/);
assert.match(html, /id="github-token" type="password" autocomplete="off"/);
assert.doesNotMatch(html, /localStorage|sessionStorage/);
'''
        subprocess.run([shutil.which("node"), "-e", script], cwd=ROOT, check=True, capture_output=True, text=True)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JavaScript behavior checks")
    def test_connection_and_japanese_admin_helpers(self) -> None:
        script = r'''
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
let status = 401;
const code = vm.createContext({
  PropertiesService: {getScriptProperties: () => ({getProperty: name => ({
    GITHUB_OWNER: "owner", GITHUB_REPOSITORY: "repo", GITHUB_TOKEN: "test-token"
  })[name]})},
  UrlFetchApp: {fetch: () => ({getResponseCode: () => status})}
});
vm.runInContext(fs.readFileSync("gas/Code.gs", "utf8"), code);
assert.equal(code.githubWorkflowConnection_().connected, false);
assert.match(code.githubWorkflowConnection_().message, /認証/);
status = 200;
assert.equal(code.githubWorkflowConnection_().connected, true);
code.UrlFetchApp.fetch = () => {throw Error("private detail")};
assert.doesNotMatch(code.githubWorkflowConnection_().message, /private detail/);
const ui = vm.createContext({document: {querySelectorAll: () => [], getElementById: () => ({addEventListener: () => {}})}});
const html = fs.readFileSync("gas/Index.html", "utf8");
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1].replace(/\n    loadData\(\);/, ""), ui);
assert.equal(ui.reviewReasonText("DATE_UNKNOWN\nFEE_UNKNOWN"), "開催日が不明・参加費が不明");
assert.match(ui.reviewReasonText("FEE_TEXT_EVIDENCE_MISMATCH\nAI_SOURCE_CHANGED"), /原文と一致しないAI抽出は不採用・AI抽出後に原文が更新/);
assert.doesNotMatch(ui.shortDate("2026-11-01T00:00:00+09:00", "date"), /00:00/);
assert.equal(ui.sourceMessageText("0件 / PUBLIC_SEMINAR_LIST_EMPTY"), "0件 / 公開セミナー欄は0件");
const now = Date.parse("2026-10-13T00:00:00+09:00");
assert.equal(ui.isUpcomingEvent({event_start_at: "2026-10-12T10:00:00+09:00"}, now), false);
assert.equal(ui.isUpcomingEvent({format:"Web", event_start_at:"2026-06-07T10:00:00+09:00", stream_end_at:"2026-11-01T00:00:00+09:00", effective_end_at:"2026-11-01T00:00:00+09:00"}, now),false);
assert.equal(ui.isUpcomingEvent({format:"Web", event_start_at:"2026-06-07T10:00:00+09:00", event_end_at:"2026-10-25T16:00:00+09:00"}, now),false);
assert.equal(ui.isUpcomingEvent({format:"Web", event_start_at:"2026-10-13T10:00:00+09:00", event_end_at:"2026-10-13T12:00:00+09:00"}, now),true);
assert.equal(ui.isUpcomingEvent({stream_start_at: "2026-09-01T00:00:00+09:00", stream_end_at: "2026-11-01T00:00:00+09:00"}, now), true);
assert.equal(ui.isUpcomingEvent({publication_status: "アーカイブ", event_start_at: "2026-11-01T00:00:00+09:00"}, now), false);
assert.equal(ui.isUpcomingEvent({}, now), false);
'''
        subprocess.run([shutil.which("node"), "-e", script], cwd=ROOT, check=True, capture_output=True, text=True)

    def test_web_admin_entrypoints_and_audit_are_present(self) -> None:
        code = (ROOT / "gas/Code.gs").read_text(encoding="utf-8")
        for function_name in (
            "doGet",
            "getAdminDashboard",
            "saveAdminEvent",
            "decideReviewFromAdmin",
            "requestSourceUpdateFromAdmin",
            "publishAdminSite",
        ):
            self.assertIn(f"function {function_name}(", code)
        self.assertIn('"ReviewActions"', code)
        self.assertNotRegex(code, r"github_pat_[A-Za-z0-9_]{20,}")

    def test_admin_html_has_required_views_and_uses_text_content(self) -> None:
        html = (ROOT / "gas/Index.html").read_text(encoding="utf-8")
        for view_name in (
            "view-dashboard",
            "view-events",
            "view-reviews",
            "view-sources",
            "view-rollout",
        ):
            self.assertIn(f'id="{view_name}"', html)
        self.assertIn("google.script.run", html)
        self.assertIn("textContent", html)
        self.assertNotIn(".innerHTML", html)

    def test_manifest_has_required_scopes(self) -> None:
        manifest = json.loads(
            (ROOT / "gas/appsscript.json").read_text(encoding="utf-8")
        )
        scopes = set(manifest["oauthScopes"])
        self.assertIn(
            "https://www.googleapis.com/auth/spreadsheets",
            scopes,
        )
        self.assertIn(
            "https://www.googleapis.com/auth/script.external_request",
            scopes,
        )


if __name__ == "__main__":
    unittest.main()
