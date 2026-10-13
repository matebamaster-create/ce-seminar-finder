from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GasAdminTest(unittest.TestCase):
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
const now = Date.parse("2026-10-13T00:00:00+09:00");
assert.equal(ui.isUpcomingEvent({event_start_at: "2026-10-12T10:00:00+09:00"}, now), false);
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
        self.assertNotIn("github_pat_", code)

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
