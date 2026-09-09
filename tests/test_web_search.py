import io
import json
import os
import unittest
from unittest import mock

from connectors import web_search


DDG_HTML = """
<html><body>
<a rel="nofollow" class="result__a"
 href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DdQw4w9WgXcQ&amp;rut=abc">
 Atomic Habits Summary</a>
<a rel="nofollow" class="result__a"
 href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&amp;rut=def">Not a video</a>
<a rel="nofollow" class="result__a"
 href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fyoutu.be%2F9bZkp7q19f0&amp;rut=ghi">
 Second <b>Video</b> &amp; More</a>
</body></html>
"""

YT_API_JSON = json.dumps({
    "items": [
        {"id": {"videoId": "dQw4w9WgXcQ"},
         "snippet": {"title": "Atomic Habits Full Summary", "channelTitle": "Book Channel"}},
        {"id": {"kind": "youtube#channel"},
         "snippet": {"title": "A Channel", "channelTitle": "A Channel"}},
        {"id": {"videoId": "short"},
         "snippet": {"title": "Bad Id", "channelTitle": "X"}},
        {"id": {"videoId": "9bZkp7q19f0"},
         "snippet": {"title": "Second Video", "channelTitle": "Music Channel"}},
    ]
})


def _resp(payload: bytes):
    stream = io.BytesIO(payload)
    stream.__enter__ = lambda self: self
    stream.__exit__ = lambda self, *a: False
    return stream


class UrlVerifyTests(unittest.TestCase):
    def test_watch_url_is_accepted_and_strips_tracking(self):
        self.assertEqual(
            web_search.verify_youtube_url(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1&si=xyz&t=42"),
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_short_and_embed_urls_are_normalized(self):
        self.assertEqual(
            web_search.verify_youtube_url("https://youtu.be/dQw4w9WgXcQ?si=1"),
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(
            web_search.verify_youtube_url("https://www.youtube.com/shorts/dQw4w9WgXcQ"),
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_non_video_urls_are_rejected(self):
        for bad in ("https://example.com/watch?v=dQw4w9WgXcQ",
                    "https://www.youtube.com/playlist?list=PL1",
                    "https://www.youtube.com/watch?v=short",
                    "https://www.youtube.com/watch",
                    "javascript:alert(1)",
                    "",
                    None):
            self.assertIsNone(web_search.verify_youtube_url(bad), bad)

    def test_lookalike_hosts_are_rejected(self):
        self.assertIsNone(
            web_search.verify_youtube_url("https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ"))


class IntentTests(unittest.TestCase):
    def test_arabic_and_english_requests_match(self):
        for text in ("أرسل روابط يوتيوب عن العادات الذرية",
                     "ابحث لي عن فيديو يشرح الفصل الثاني",
                     "هات مقاطع يوتيوب للمراجعة",
                     "send me youtube links for atomic habits",
                     "find videos explaining chapter 2"):
            self.assertTrue(web_search.is_video_link_request(text), text)

    def test_plain_mentions_and_negations_do_not_match(self):
        for text in ("ما هو اليوتيوب؟",
                     "شاهدت فيديو جميل أمس",
                     "لا ترسل روابط يوتيوب",
                     "",
                     "what time is my meeting"):
            self.assertFalse(web_search.is_video_link_request(text), text)

    def test_message_already_containing_links_is_detected(self):
        self.assertTrue(web_search.answer_has_video_links(
            "see https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        self.assertFalse(web_search.answer_has_video_links("no links here"))


class SanitizeTests(unittest.TestCase):
    def test_private_identifiers_are_stripped(self):
        clean = web_search.sanitize_query(
            "/youtube ملخص العادات 0551234567 me@test.com 1088123456")
        self.assertNotIn("0551234567", clean)
        self.assertNotIn("me@test.com", clean)
        self.assertNotIn("1088123456", clean)
        self.assertIn("ملخص العادات", clean)

    def test_query_is_bounded(self):
        self.assertLessEqual(len(web_search.sanitize_query("x" * 500)), 200)


class ProviderTests(unittest.TestCase):
    def setUp(self):
        web_search._CACHE.clear()

    def test_ddg_provider_keeps_only_verified_videos(self):
        with mock.patch.object(web_search.urllib.request, "urlopen",
                               return_value=_resp(DDG_HTML.encode())):
            out = web_search.search_videos("atomic habits", provider="ddg")
        self.assertTrue(out["ok"])
        self.assertEqual(out["provider"], "ddg")
        urls = [r["url"] for r in out["results"]]
        self.assertEqual(urls, ["https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                                "https://www.youtube.com/watch?v=9bZkp7q19f0"])
        self.assertEqual(out["results"][0]["title"], "Atomic Habits Summary")
        self.assertIn("Second Video", out["results"][1]["title"])

    def test_youtube_api_provider_parses_items(self):
        with mock.patch.object(web_search.urllib.request, "urlopen",
                               return_value=_resp(YT_API_JSON.encode())), \
                mock.patch.dict(os.environ, {"YOUTUBE_API_KEY": "k"}):
            out = web_search.search_videos("atomic habits", provider="youtube_api")
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["results"]), 2)
        self.assertEqual(out["results"][0]["channel"], "Book Channel")

    def test_api_failure_falls_back_to_ddg(self):
        calls = []

        def fake_fetch(url, timeout, params=None):
            calls.append(url)
            if "googleapis" in url:
                raise RuntimeError("quota exceeded")
            return DDG_HTML.encode()

        with mock.patch.object(web_search, "_fetch", side_effect=fake_fetch), \
                mock.patch.dict(os.environ, {"YOUTUBE_API_KEY": "k"}):
            out = web_search.search_videos("atomic habits")
        self.assertTrue(out["ok"])
        self.assertEqual(out["provider"], "ddg")
        self.assertEqual(len(calls), 2)

    def test_failures_are_soft_and_never_raise(self):
        with mock.patch.object(web_search, "_fetch", side_effect=Exception("net down")), \
                mock.patch.dict(os.environ, {}, clear=True):
            out = web_search.search_videos("x")
        self.assertFalse(out["ok"])
        self.assertEqual(out["results"], [])
        self.assertIn("net down", out["error"])

    def test_results_are_cached(self):
        with mock.patch.object(web_search, "_fetch",
                               return_value=DDG_HTML.encode()) as fake:
            first = web_search.search_videos("cached query", provider="ddg")
            second = web_search.search_videos("cached query", provider="ddg")
        self.assertTrue(first["ok"] and second["ok"])
        self.assertEqual(second["provider"], "ddg+cache")
        fake.assert_called_once()

    def test_empty_query_short_circuits(self):
        out = web_search.search_videos("   ")
        self.assertFalse(out["ok"])


class FormatTests(unittest.TestCase):
    RESULTS = [{"title": "T1", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "channel": "C1"},
               {"title": "T2", "url": "https://www.youtube.com/watch?v=9bZkp7q19f0",
                "channel": ""}]

    def test_links_section_is_clickable_and_counted(self):
        section = web_search.format_links_section(self.RESULTS, "العادات")
        self.assertIn("🔗 روابط يوتيوب موثقة (2)", section)
        self.assertIn("https://www.youtube.com/watch?v=dQw4w9WgXcQ", section)
        self.assertIn("T1 — C1", section)

    def test_empty_results_give_empty_section(self):
        self.assertEqual(web_search.format_links_section([]), "")
        self.assertEqual(web_search.verified_context_block([]), "")

    def test_context_block_instructs_no_invention(self):
        block = web_search.verified_context_block(self.RESULTS, "q")
        self.assertIn("VERIFIED VIDEO LINKS", block)
        self.assertIn("Never invent", block)
        self.assertIn("https://www.youtube.com/watch?v=dQw4w9WgXcQ", block)


class BotWiringTests(unittest.TestCase):
    def test_lookup_returns_block_and_results_for_video_requests(self):
        from connectors import telegram_bot_legacy
        payload = {"ok": True, "results": FormatTests.RESULTS, "provider": "ddg", "error": ""}
        with mock.patch.object(web_search, "search_videos", return_value=payload):
            block, results = telegram_bot_legacy._verified_video_lookup(
                "أرسل روابط يوتيوب عن العادات الذرية")
        self.assertEqual(len(results), 2)
        self.assertIn("VERIFIED VIDEO LINKS", block)

    def test_lookup_stays_silent_for_normal_messages(self):
        from connectors import telegram_bot_legacy
        with mock.patch.object(web_search, "search_videos") as fake:
            block, results = telegram_bot_legacy._verified_video_lookup("ما مواعيد اليوم؟")
        self.assertEqual((block, results), ("", []))
        fake.assert_not_called()

    def test_lookup_is_fail_soft(self):
        from connectors import telegram_bot_legacy
        with mock.patch.object(web_search, "search_videos", side_effect=Exception("boom")):
            self.assertEqual(telegram_bot_legacy._verified_video_lookup(
                "send youtube links"), ("", []))

    def test_youtube_command_sends_links(self):
        from connectors import telegram_bot_legacy
        payload = {"ok": True, "results": FormatTests.RESULTS, "provider": "ddg", "error": ""}
        with mock.patch.object(web_search, "search_videos", return_value=payload), \
                mock.patch.object(telegram_bot_legacy, "send") as fake_send:
            telegram_bot_legacy.command_youtube(1, "العادات الذرية")
        combined = "\n".join(c.args[1] for c in fake_send.call_args_list)
        self.assertIn("youtube.com/watch?v=", combined)

    def test_youtube_command_needs_a_query(self):
        from connectors import telegram_bot_legacy
        with mock.patch.object(telegram_bot_legacy, "send") as fake_send:
            telegram_bot_legacy.command_youtube(1, "   ")
        self.assertIn("/youtube", fake_send.call_args[0][1])


if __name__ == "__main__":
    unittest.main()
