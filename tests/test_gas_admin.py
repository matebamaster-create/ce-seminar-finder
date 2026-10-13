from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GasAdminTest(unittest.TestCase):
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
