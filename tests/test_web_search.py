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

    def test_handle_message_routes_youtube_command(self):
        from connectors import telegram_bot_legacy
        payload = {"ok": True, "results": FormatTests.RESULTS, "provider": "ddg", "error": ""}
        with mock.patch.object(web_search, "search_videos", return_value=payload), \
                mock.patch.object(telegram_bot_legacy, "_authorized", return_value=True), \
                mock.patch.object(telegram_bot_legacy, "_local_capture", return_value="TG-1"), \
                mock.patch.object(telegram_bot_legacy, "_save_intake", return_value=True), \
                mock.patch.object(telegram_bot_legacy, "send") as fake_send:
            telegram_bot_legacy.handle_message({
                "chat": {"id": 1, "type": "private"},
                "text": "/youtube العادات الذرية",
            })
        combined = "\n".join(c.args[1] for c in fake_send.call_args_list)
        self.assertIn("youtube.com/watch?v=", combined)
        self.assertNotIn("أمر غير معروف", combined)

    def test_natural_request_appends_links_when_model_omits_them(self):
        from connectors import telegram_bot_legacy
        payload = {"ok": True, "results": FormatTests.RESULTS, "provider": "ddg", "error": ""}
        with mock.patch.object(web_search, "search_videos", return_value=payload), \
                mock.patch.object(telegram_bot_legacy, "_authorized", return_value=True), \
                mock.patch.object(telegram_bot_legacy, "_local_capture", return_value="TG-1"), \
                mock.patch.object(telegram_bot_legacy, "_save_intake", return_value=True), \
                mock.patch.object(telegram_bot_legacy, "_save_conversation", return_value=True), \
                mock.patch.object(telegram_bot_legacy, "api", return_value={}), \
                mock.patch("agent_runtime.remember"), \
                mock.patch.object(
                    telegram_bot_legacy, "ask_bedrock",
                    return_value=("هذه ملخصات مفيدة بدون روابط.", {}, 1, []),
                ) as fake_ask, \
                mock.patch.object(telegram_bot_legacy, "send") as fake_send:
            telegram_bot_legacy.handle_message({
                "chat": {"id": 1, "type": "private", "message_id": 9},
                "message_id": 9,
                "text": "أرسل روابط يوتيوب عن العادات الذرية",
            })
        self.assertIn("VERIFIED VIDEO LINKS", fake_ask.call_args.kwargs["sheet_context"])
        sent = fake_send.call_args[0][1]
        self.assertIn("youtube.com/watch?v=", sent)


TAVILY_JSON = json.dumps({
    "query": "knee protocol",
    "answer": "The Quiet Knee Protocol is a conservative post-TKA recovery method.",
    "results": [
        {"title": "HSS Quiet Knee Study", "url": "https://news.hss.edu/quiet-knee",
         "content": "Conservative recovery after TKA reduces opioid use.", "score": 0.91},
        {"title": "Duplicate", "url": "https://news.hss.edu/quiet-knee",
         "content": "duplicate entry", "score": 0.90},
        {"title": "No URL", "content": "should be dropped", "score": 0.80},
        {"title": "Bad Scheme", "url": "ftp://example.com/x", "content": "dropped", "score": 0.70},
        {"title": "Quiet Knee Explained",
         "url": "https://corycalendinemd.com/blog/quiet-knee-protocol/",
         "content": "Calm swelling first, then strengthen around week four.", "score": 0.87},
    ],
})


def _patch_tavily_post(payload: str = TAVILY_JSON, exc=None):
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append(request)
        if exc is not None:
            raise exc
        return _resp(payload.encode("utf-8"))

    return mock.patch.object(web_search.urllib.request, "urlopen", side_effect=fake_urlopen), calls


class TavilyWebSearchTests(unittest.TestCase):
    def setUp(self):
        web_search._CACHE.clear()

    def test_missing_key_fails_soft_without_network(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(web_search.urllib.request, "urlopen") as fake:
            out = web_search.web_search("knee protocol")
        self.assertFalse(out["ok"])
        self.assertEqual(out["results"], [])
        self.assertEqual(out["answer"], "")
        self.assertIn("TAVILY_API_KEY", out["error"])
        fake.assert_not_called()

    def test_parses_and_filters_results(self):
        patcher, calls = _patch_tavily_post()
        with patcher, mock.patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test"}):
            out = web_search.web_search("knee protocol")
        self.assertTrue(out["ok"])
        self.assertEqual(out["provider"], "tavily")
        self.assertEqual(out["answer"],
                         "The Quiet Knee Protocol is a conservative post-TKA recovery method.")
        urls = [r["url"] for r in out["results"]]
        self.assertEqual(urls, ["https://news.hss.edu/quiet-knee",
                                "https://corycalendinemd.com/blog/quiet-knee-protocol/"])
        self.assertIn("opioid", out["results"][0]["snippet"].lower())
        self.assertEqual(len(calls), 1)

    def test_request_sanitizes_and_bears_key(self):
        patcher, calls = _patch_tavily_post()
        with patcher, mock.patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test"}):
            out = web_search.web_search("search knee 0551234567 a@b.com")
        self.assertTrue(out["ok"])
        request = calls[0]
        self.assertEqual(request.full_url, "https://api.tavily.com/search")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer tvly-test")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["query"], "search knee")
        self.assertNotIn("0551234567", body["query"])
        self.assertNotIn("a@b.com", body["query"])
        self.assertEqual(body["search_depth"], "basic")
        self.assertEqual(body["topic"], "general")
        self.assertTrue(body["include_answer"])

    def test_custom_base_url_and_depth_normalization(self):
        patcher, calls = _patch_tavily_post()
        with patcher, mock.patch.dict(os.environ,
                                      {"TAVILY_API_KEY": "k",
                                       "TAVILY_BASE_URL": "https://tv.example.com/v1"}):
            out = web_search.web_search("knee", search_depth="  ADVANCED ", topic="NEWS")
        self.assertTrue(out["ok"])
        self.assertEqual(calls[0].full_url, "https://tv.example.com/v1/search")
        body = json.loads(calls[0].data.decode("utf-8"))
        self.assertEqual(body["search_depth"], "advanced")
        self.assertEqual(body["topic"], "news")

    def test_http_error_fails_soft(self):
        exc = web_search.urllib.error.HTTPError("u", 401, "bad key", {}, None)
        patcher, _ = _patch_tavily_post(exc=exc)
        with patcher, mock.patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test"}):
            out = web_search.web_search("knee")
        self.assertFalse(out["ok"])
        self.assertEqual(out["results"], [])
        self.assertIn("tavily", out["error"])
        self.assertIn("401", out["error"])

    def test_results_are_cached(self):
        patcher, calls = _patch_tavily_post()
        with patcher, mock.patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test"}):
            first = web_search.web_search("knee protocol")
            second = web_search.web_search("knee protocol")
        self.assertTrue(first["ok"] and second["ok"])
        self.assertEqual(second["provider"], "tavily+cache")
        self.assertEqual(len(calls), 1)

    def test_empty_query_short_circuits(self):
        out = web_search.web_search("   ")
        self.assertFalse(out["ok"])
        self.assertEqual(out["results"], [])


class WebIntentTests(unittest.TestCase):
    def test_explicit_research_triggers(self):
        for text in ("ابحث عن بروتوكول الركبة", "Search knee protocol",
                     "قارن بين بروتوكولي التعافي", "latest TKA outcomes report",
                     "ابحث عن مصادر لبروتوكول الركبة", "compare the two knee protocols"):
            self.assertTrue(web_search.is_web_search_request(text), text)

    def test_video_requests_do_not_trigger(self):
        for text in ("أرسل روابط يوتيوب عن العادات", "send youtube links about knees",
                     "ابحث عن فيديو بروتوكول الركبة"):
            self.assertFalse(web_search.is_web_search_request(text), text)

    def test_normal_chat_does_not_trigger(self):
        for text in ("وش الوقت؟", "ما مواعيد اليوم؟", "متى جلسة العلاج؟",
                     "ما هو أفضل وقت للتدرب؟", "hi"):
            self.assertFalse(web_search.is_web_search_request(text), text)


class WebFormatTests(unittest.TestCase):
    RESULTS = [{"title": "HSS Study", "url": "https://news.hss.edu/quiet-knee",
                "snippet": "Conservative recovery reduces opioids.", "score": 0.9},
               {"title": "Explainer",
                "url": "https://corycalendinemd.com/blog/quiet-knee-protocol/",
                "snippet": "", "score": 0.8}]

    def test_web_section_lists_sources(self):
        section = web_search.format_web_section(self.RESULTS, "knee protocol")
        self.assertIn("نتائج ويب موثقة (2)", section)
        self.assertIn("https://news.hss.edu/quiet-knee", section)
        self.assertIn("Conservative recovery reduces opioids.", section)

    def test_empty_results_give_empty_section(self):
        self.assertEqual(web_search.format_web_section([]), "")
        self.assertEqual(web_search.web_context_block([]), "")

    def test_web_context_block_grounds_the_model(self):
        block = web_search.web_context_block(self.RESULTS, "knee", "answer text")
        self.assertIn("VERIFIED WEB SEARCH RESULTS", block)
        self.assertIn("answer text", block)
        self.assertIn("https://news.hss.edu/quiet-knee", block)

    def test_providers_status_reports_configuration(self):
        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": "k", "YOUTUBE_API_KEY": "y"}):
            status = web_search.providers_status()
        self.assertEqual(status["web"], {"provider": "tavily", "configured": True})
        self.assertTrue(status["video"]["youtube_api"])
        with mock.patch.dict(os.environ, {}, clear=True):
            status = web_search.providers_status()
        self.assertFalse(status["web"]["configured"])
        self.assertFalse(status["video"]["youtube_api"])


class WebBotWiringTests(unittest.TestCase):
    PAYLOAD = {"ok": True, "provider": "tavily",
               "answer": "Quiet Knee protocol summary.",
               "results": WebFormatTests.RESULTS, "error": ""}

    def test_web_lookup_returns_block_for_research_requests(self):
        from connectors import telegram_bot_legacy
        with mock.patch.object(web_search, "web_search", return_value=self.PAYLOAD), \
                mock.patch.dict(os.environ, {"TAVILY_API_KEY": "k"}):
            block, results, answer = telegram_bot_legacy._verified_web_lookup(
                "ابحث عن بروتوكول الركبة")
        self.assertEqual(len(results), 2)
        self.assertIn("VERIFIED WEB SEARCH RESULTS", block)
        self.assertEqual(answer, "Quiet Knee protocol summary.")

    def test_web_lookup_stays_silent_without_key(self):
        from connectors import telegram_bot_legacy
        with mock.patch.object(web_search, "web_search") as fake, \
                mock.patch.dict(os.environ, {}, clear=True):
            block, results, answer = telegram_bot_legacy._verified_web_lookup(
                "ابحث عن بروتوكول الركبة")
        self.assertEqual((block, results, answer), ("", [], ""))
        fake.assert_not_called()

    def test_web_lookup_ignores_normal_messages(self):
        from connectors import telegram_bot_legacy
        with mock.patch.object(web_search, "web_search") as fake, \
                mock.patch.dict(os.environ, {"TAVILY_API_KEY": "k"}):
            block, results, answer = telegram_bot_legacy._verified_web_lookup(
                "ما مواعيد اليوم؟")
        self.assertEqual((block, results, answer), ("", [], ""))
        fake.assert_not_called()

    def test_web_lookup_is_fail_soft(self):
        from connectors import telegram_bot_legacy
        with mock.patch.object(web_search, "web_search", side_effect=Exception("boom")), \
                mock.patch.dict(os.environ, {"TAVILY_API_KEY": "k"}):
            self.assertEqual(
                telegram_bot_legacy._verified_web_lookup("search knee protocol"),
                ("", [], ""))

    def test_websearch_command_sends_sources_and_answer(self):
        from connectors import telegram_bot_legacy
        with mock.patch.object(web_search, "web_search", return_value=self.PAYLOAD), \
                mock.patch.dict(os.environ, {"TAVILY_API_KEY": "k"}), \
                mock.patch.object(telegram_bot_legacy, "send") as fake_send:
            telegram_bot_legacy.command_websearch(1, "knee protocol")
        combined = "\n".join(c.args[1] for c in fake_send.call_args_list)
        self.assertIn("https://news.hss.edu/quiet-knee", combined)
        self.assertIn("Quiet Knee protocol summary.", combined)

    def test_websearch_command_requires_key(self):
        from connectors import telegram_bot_legacy
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(telegram_bot_legacy, "send") as fake_send:
            telegram_bot_legacy.command_websearch(1, "knee protocol")
        combined = "\n".join(c.args[1] for c in fake_send.call_args_list)
        self.assertIn("TAVILY_API_KEY", combined)

    def test_websearch_command_needs_a_query(self):
        from connectors import telegram_bot_legacy
        with mock.patch.object(telegram_bot_legacy, "send") as fake_send:
            telegram_bot_legacy.command_websearch(1, "   ")
        self.assertIn("/websearch", fake_send.call_args[0][1])

    def test_handle_message_routes_websearch_command(self):
        from connectors import telegram_bot_legacy
        with mock.patch.object(web_search, "web_search", return_value=self.PAYLOAD), \
                mock.patch.dict(os.environ, {"TAVILY_API_KEY": "k"}), \
                mock.patch.object(telegram_bot_legacy, "_authorized", return_value=True), \
                mock.patch.object(telegram_bot_legacy, "_local_capture", return_value="TG-1"), \
                mock.patch.object(telegram_bot_legacy, "_save_intake", return_value=True), \
                mock.patch.object(telegram_bot_legacy, "send") as fake_send:
            telegram_bot_legacy.handle_message({
                "chat": {"id": 1, "type": "private"},
                "text": "/websearch بروتوكول الركبة",
            })
        combined = "\n".join(c.args[1] for c in fake_send.call_args_list)
        self.assertIn("https://news.hss.edu/quiet-knee", combined)
        self.assertNotIn("أمر غير معروف", combined)

    def test_natural_research_request_injects_web_context(self):
        from connectors import telegram_bot_legacy
        with mock.patch.object(web_search, "web_search", return_value=self.PAYLOAD), \
                mock.patch.dict(os.environ, {"TAVILY_API_KEY": "k"}), \
                mock.patch.object(telegram_bot_legacy, "_authorized", return_value=True), \
                mock.patch.object(telegram_bot_legacy, "_local_capture", return_value="TG-1"), \
                mock.patch.object(telegram_bot_legacy, "_save_intake", return_value=True), \
                mock.patch.object(telegram_bot_legacy, "_save_conversation", return_value=True), \
                mock.patch.object(telegram_bot_legacy, "api", return_value={}), \
                mock.patch("agent_runtime.remember"), \
                mock.patch.object(
                    telegram_bot_legacy, "ask_bedrock",
                    return_value=("إجابة بدون روابط.", {}, 1, []),
                ) as fake_ask, \
                mock.patch.object(telegram_bot_legacy, "send") as fake_send:
            telegram_bot_legacy.handle_message({
                "chat": {"id": 1, "type": "private", "message_id": 9},
                "message_id": 9,
                "text": "ابحث عن بروتوكول الركبة",
            })
        self.assertIn("VERIFIED WEB SEARCH RESULTS", fake_ask.call_args.kwargs["sheet_context"])
        sent = fake_send.call_args[0][1]
        self.assertIn("https://news.hss.edu/quiet-knee", sent)

    def test_natural_request_without_key_skips_web_lookup(self):
        from connectors import telegram_bot_legacy
        with mock.patch.object(web_search, "web_search") as fake_web, \
                mock.patch.object(web_search, "search_videos") as fake_video, \
                mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(telegram_bot_legacy, "_authorized", return_value=True), \
                mock.patch.object(telegram_bot_legacy, "_local_capture", return_value="TG-1"), \
                mock.patch.object(telegram_bot_legacy, "_save_intake", return_value=True), \
                mock.patch.object(telegram_bot_legacy, "_save_conversation", return_value=True), \
                mock.patch.object(telegram_bot_legacy, "api", return_value={}), \
                mock.patch("agent_runtime.remember"), \
                mock.patch.object(
                    telegram_bot_legacy, "ask_bedrock",
                    return_value=("إجابة عادية.", {}, 1, []),
                ) as fake_ask, \
                mock.patch.object(telegram_bot_legacy, "send") as fake_send:
            telegram_bot_legacy.handle_message({
                "chat": {"id": 1, "type": "private", "message_id": 9},
                "message_id": 9,
                "text": "ابحث عن بروتوكول الركبة",
            })
        fake_web.assert_not_called()
        fake_video.assert_not_called()
        self.assertNotIn("VERIFIED WEB SEARCH RESULTS", fake_ask.call_args.kwargs["sheet_context"])
        self.assertEqual(fake_send.call_args[0][1], "إجابة عادية.")


class WebCliTests(unittest.TestCase):
    def setUp(self):
        web_search._CACHE.clear()

    def test_web_flag_prints_sources_and_answer(self):
        patcher, _ = _patch_tavily_post()
        with patcher, mock.patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test"}), \
                mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = web_search.main(["--web", "knee protocol"])
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("https://news.hss.edu/quiet-knee", text)
        self.assertIn("Quiet Knee Protocol", text)

    def test_web_flag_without_key_fails(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = web_search.main(["--web", "knee protocol"])
        self.assertEqual(rc, 1)
        self.assertIn("TAVILY_API_KEY", out.getvalue())

    def test_check_reports_providers(self):
        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test"}), \
                mock.patch.object(web_search, "web_search", return_value={
                    "ok": True, "provider": "tavily", "answer": "",
                    "results": [{"url": "u"}], "error": ""}), \
                mock.patch.object(web_search, "search_videos", return_value={
                    "ok": True, "provider": "ddg", "results": [{"url": "u"}],
                    "answer": "", "error": ""}), \
                mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = web_search.main(["--check"])
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("tavily", text)
        self.assertIn("video", text)


class GuideTests(unittest.TestCase):
    def test_videosearch_guide_is_registered(self):
        from connectors import connection_setup
        with mock.patch("builtins.print") as printer:
            self.assertEqual(connection_setup.main(["--guide", "videosearch"]), 0)
        text = "\n".join(str(call.args[0]) for call in printer.call_args_list)
        self.assertIn("YOUTUBE_API_KEY", text)
        self.assertIn("/youtube", text)

    def test_websearch_guide_is_registered(self):
        from connectors import connection_setup
        with mock.patch("builtins.print") as printer:
            self.assertEqual(connection_setup.main(["--guide", "websearch"]), 0)
        text = "\n".join(str(call.args[0]) for call in printer.call_args_list)
        self.assertIn("TAVILY_API_KEY", text)
        self.assertIn("/websearch", text)


if __name__ == "__main__":
    unittest.main()
