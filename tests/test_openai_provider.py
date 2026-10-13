from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from ce_seminar_finder.extraction.models import ExtractionRequest
from ce_seminar_finder.extraction.openai_provider import OpenAIProvider, OpenAIExtractionError, load_api_key
from ce_seminar_finder.extraction.prompt import PROMPT_VERSION
from ce_seminar_finder.extraction.service import ExtractionService
from ce_seminar_finder.extraction.validator import validate_extraction


def request():
    return ExtractionRequest("src_test", "https://example.test/event", "開催日時 2026年11月20日 18:00～20:00\n参加費 会員無料、非会員500円",
        ("https://example.test/event",), title_hint="呼吸セミナー")


def response(raw):
    return {"status": "completed", "usage": {"input_tokens": 100, "output_tokens": 50}, "output": [
        {"type": "message", "content": [{"type": "output_text", "text": json.dumps(raw, ensure_ascii=False)}]}]}


class OpenAIProviderTest(unittest.TestCase):
    def test_uses_strict_schema_bounded_requests_and_no_storage_or_secret_in_body(self):
        bodies = []
        def transport(body):
            bodies.append(body)
            return response({"is_event": True, "event_confidence": .95, "fields": {}, "review_reasons": []})
        provider = OpenAIProvider("test-secret", max_requests=1, transport=transport)
        provider.extract_event(request())
        body = bodies[0]
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertFalse(body["store"])
        self.assertFalse(body["text"]["format"]["schema"]["additionalProperties"])
        self.assertNotIn("tools", body)
        self.assertNotIn("test-secret", json.dumps(body))
        self.assertEqual((100, 50), (provider.input_tokens, provider.output_tokens))
        with self.assertRaisesRegex(OpenAIExtractionError, "REQUEST_LIMIT_REACHED"):
            provider.extract_event(request())

    def test_does_not_send_oversize_input(self):
        provider = OpenAIProvider("test-secret", max_input_chars=100, transport=lambda body: self.fail("must not call"))
        with self.assertRaisesRegex(OpenAIExtractionError, "INPUT_LIMIT_REACHED"):
            provider.extract_event(request())
        self.assertEqual(0, provider.requests)

    def test_refusal_incomplete_and_invalid_json_are_not_accepted(self):
        for raw, code in [({"status": "incomplete"}, "RESPONSE_INCOMPLETE"),
            ({"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal"}]}]}, "RESPONSE_REFUSED"),
            ({"status": "completed", "output": []}, "INVALID_JSON")]:
            with self.subTest(code=code):
                provider = OpenAIProvider("test-secret", transport=lambda body: raw)
                with self.assertRaisesRegex(OpenAIExtractionError, code):
                    provider.extract_event(request())

    def test_transport_and_http_errors_do_not_expose_credentials(self):
        def fail(body): raise RuntimeError("test-secret")
        provider = OpenAIProvider("test-secret", transport=fail)
        with self.assertRaises(OpenAIExtractionError) as captured:
            provider.extract_event(request())
        self.assertNotIn("test-secret", str(captured.exception))
        class Opener:
            def open(self, *args, **kwargs):
                raise HTTPError("https://api.openai.com/v1/responses", 429, "test-secret", {},
                    io.BytesIO(b'{"error":{"code":"insufficient_quota","message":"test-secret"}}'))
        with patch("urllib.request.build_opener", return_value=Opener()):
            with self.assertRaises(OpenAIExtractionError) as captured:
                OpenAIProvider("test-secret").extract_event(request())
        self.assertEqual("insufficient_quota", captured.exception.code)
        self.assertNotIn("test-secret", str(captured.exception))

    def test_reads_only_explicit_env_file_or_environment(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            path = Path(directory) / ".env.local"
            with self.assertRaisesRegex(OpenAIExtractionError, "API_KEY_MISSING"):
                load_api_key(path)
            path.write_text("OTHER=value\nOPENAI_API_KEY=test-secret\n")
            self.assertEqual("test-secret", load_api_key(path))


class GroundingTest(unittest.TestCase):
    def validate(self, fields):
        return validate_extraction({"is_event": True, "event_confidence": 1, "fields": fields},
            allowed_urls=request().allowed_urls, provider="openai", model="test", prompt_version=PROMPT_VERSION,
            source_text=request().candidate_text)

    def test_invented_evidence_and_wrong_date_are_rejected(self):
        result = self.validate({"fee_text": {"value": "1000円", "confidence": 1, "evidence": "参加費1000円"},
            "event_start": {"value": "2027-11-20T18:00:00+09:00", "confidence": 1, "evidence": "開催日時 2026年11月20日 18:00～20:00"}})
        self.assertIsNone(result.fields["fee_text"].value)
        self.assertIsNone(result.fields["event_start"].value)

    def test_real_evidence_cannot_support_wrong_amount_or_conditional_free(self):
        result = self.validate({"fee_text": {"value": "非会員5000円", "confidence": 1, "evidence": "参加費 会員無料、非会員500円"},
            "fee_category": {"value": "無料", "confidence": 1, "evidence": "参加費 会員無料、非会員500円"}})
        self.assertIsNone(result.fields["fee_text"].value)
        self.assertIsNone(result.fields["fee_category"].value)

    def test_incomplete_fee_label_is_not_used(self):
        result = self.validate({"fee_text": {"value": "会員:、非会員500円", "confidence": 1,
            "evidence": "参加費 会員無料、非会員500円"}})
        self.assertIsNone(result.fields["fee_text"].value)
        self.assertIn("FEE_TEXT_INCOMPLETE", result.review_reasons)

    def test_yen_symbol_paid_nonmember_is_not_free(self):
        result = validate_extraction({"is_event": True, "fields": {"fee_category": {
            "value": "無料", "confidence": 1, "evidence": "会員無料、非会員￥500"}}},
            allowed_urls=(), provider="openai", model="test", prompt_version=PROMPT_VERSION,
            source_text="会員無料、非会員￥500")
        self.assertIsNone(result.fields["fee_category"].value)

    def test_fee_amounts_cannot_be_swapped_between_roles(self):
        text = "会員500円、非会員1000円"
        result = validate_extraction({"is_event": True, "fields": {"fee_text": {
            "value": "会員1000円、非会員500円", "confidence": 1, "evidence": text}}},
            allowed_urls=(), provider="openai", model="test", prompt_version=PROMPT_VERSION, source_text=text)
        self.assertIsNone(result.fields["fee_text"].value)

    def test_publication_date_is_not_adopted_as_event_date(self):
        text = "掲載日 2026年11月20日"
        result = validate_extraction({"is_event": True, "fields": {"event_start": {
            "value": "2026-11-20T00:00:00+09:00", "confidence": 1, "evidence": text}}},
            allowed_urls=(), provider="openai", model="test", prompt_version=PROMPT_VERSION, source_text=text)
        self.assertIsNone(result.fields["event_start"].value)

    def test_datetime_is_normalized_to_japan_time(self):
        result = self.validate({"event_start": {"value": "2026-11-20T09:00:00Z", "confidence": 1,
            "evidence": "開催日時 2026年11月20日 18:00～20:00"}})
        self.assertEqual("2026-11-20T18:00:00+09:00", result.fields["event_start"].value)

    def test_grounded_time_range_end_is_accepted(self):
        result = self.validate({"event_end": {"value": "2026-11-20T20:00:00+09:00", "confidence": 1,
            "evidence": "開催日時 2026年11月20日 18:00～20:00"}})
        self.assertEqual("2026-11-20T20:00:00+09:00", result.fields["event_end"].value)

    def test_discovered_url_is_grounded_by_allowlist_not_body_quote(self):
        result = self.validate({"official_url": {"value": "https://example.test/event", "confidence": 1,
            "evidence": "https://example.test/event"}})
        self.assertEqual("https://example.test/event", result.fields["official_url"].value)

    def test_service_revalidates_cached_evidence_against_input(self):
        raw = {"is_event": True, "event_confidence": 1, "fields": {"organizer": {
            "value": "存在しない主催者", "confidence": 1, "evidence": "存在しない主催者"}}}
        provider = OpenAIProvider("test-secret", transport=lambda body: response(raw))
        class Cache:
            def get(self, key): return raw
            def put(self, key, value): raise AssertionError("cached result must not be written again")
        result = ExtractionService(provider, prompt_version=PROMPT_VERSION, cache=Cache()).extract(request())
        self.assertIsNone(result.fields["organizer"].value)
        self.assertTrue(result.cache_hit)
        self.assertEqual(0, provider.requests)
