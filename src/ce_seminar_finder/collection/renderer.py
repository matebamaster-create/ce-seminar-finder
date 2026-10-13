from __future__ import annotations
import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path


class PublicPageRenderer:
    """Optional Node Playwright worker, with no user login state or secrets."""
    def render(self, response):
        script = Path(__file__).resolve().parents[3] / "scripts/render_public.cjs"
        result = subprocess.run(["node", str(script), response.final_url],
            capture_output=True, text=True, timeout=50, check=True)
        payload = json.loads(result.stdout)
        body = payload["html"].encode()
        return replace(response, body=body, final_url=payload["url"], encoding="utf-8",
            content_hash=hashlib.sha256(body).hexdigest())
