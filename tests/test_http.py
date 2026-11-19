import httpx

from scholarship_agent.http_client import HttpFetcher, MemoryFeedCache


def test_socks4_system_proxy_is_rewritten_for_httpx():
    from scholarship_agent.http_client import normalize_proxy

    assert normalize_proxy("socks4://127.0.0.1:10808") == "socks5h://127.0.0.1:10808"
    assert normalize_proxy("http://proxy.example:8080") == "http://proxy.example:8080"
    assert normalize_proxy(None) is None


def test_conditional_get_uses_the_saved_etag():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if request.headers.get("if-none-match") == '"abc"':
            return httpx.Response(304)
        return httpx.Response(200, text="<rss>ok</rss>", headers={"ETag": '"abc"'})

    cache = MemoryFeedCache()
    fetcher = HttpFetcher(
        cache=cache,
        timeout=5,
        max_retries=1,
        user_agent="test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )
    first = fetcher.get_text("https://example.org/feed")
    second = fetcher.get_text("https://example.org/feed")
    fetcher.close()
    assert first.text == "<rss>ok</rss>"
    assert second.not_modified
    assert calls["count"] == 2


def test_full_fetch_ignores_a_saved_etag():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "if-none-match" not in request.headers
        return httpx.Response(200, text="<rss>full</rss>", headers={"ETag": '"abc"'})

    cache = MemoryFeedCache()
    cache.save_validators("https://example.org/feed", '"abc"', None)
    fetcher = HttpFetcher(
        cache=cache,
        timeout=5,
        max_retries=1,
        user_agent="test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )
    result = fetcher.get_text("https://example.org/feed", conditional=False)
    fetcher.close()
    assert result.text == "<rss>full</rss>"
    assert result.not_modified is False
