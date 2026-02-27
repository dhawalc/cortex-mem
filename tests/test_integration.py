import httpx
import pytest

import daemon_integration as daemon
import openclaw_integration as oc


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.request = httpx.Request("GET", "http://test")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("HTTP error", request=self.request, response=self)


class OpenClawFakeClient:
    def __init__(self, responses=None, get_responses=None, raises=None):
        self.responses = responses or []
        self.get_responses = get_responses or []
        self.raises = raises
        self.posts = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json):
        if self.raises:
            raise self.raises
        self.posts.append((url, json))
        if self.responses:
            return self.responses.pop(0)
        return FakeResponse(status_code=200, payload={"id": "default-id"})

    async def get(self, url):
        if self.raises:
            raise self.raises
        if self.get_responses:
            return self.get_responses.pop(0)
        return FakeResponse(status_code=200, payload={"status": "ok"})


class DaemonFakeClient:
    def __init__(self):
        self.posts = []
        self.gets = []
        self.closed = False

    async def post(self, url, json):
        self.posts.append((url, json))

        if url.endswith("/memory/weight") and "tier" not in json:
            return FakeResponse(status_code=422, payload={"detail": "tier missing"})

        if url.endswith("/error"):
            return FakeResponse(status_code=500, payload={})

        return FakeResponse(status_code=200, payload={"id": "abc123", "results": []})

    async def get(self, url):
        self.gets.append(url)
        return FakeResponse(status_code=200, payload={"status": "ok"})

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_sync_to_aoms_autodetects_entry_type_and_returns_id(monkeypatch):
    fake_client = OpenClawFakeClient(responses=[FakeResponse(200, {"id": "entry-1"})])
    monkeypatch.setattr(oc.httpx, "AsyncClient", lambda timeout=5.0: fake_client)

    entry_id = await oc.sync_to_aoms(
        tier="semantic",
        payload={"subject": "AOMS", "predicate": "is", "object": "active"},
    )

    assert entry_id == "entry-1"
    assert fake_client.posts[0][1]["type"] == "fact"


@pytest.mark.asyncio
async def test_sync_to_aoms_raises_on_error_when_not_silent(monkeypatch):
    fake_client = OpenClawFakeClient(responses=[FakeResponse(500, text="boom")])
    monkeypatch.setattr(oc.httpx, "AsyncClient", lambda timeout=5.0: fake_client)

    with pytest.raises(RuntimeError, match="AOMS sync failed"):
        await oc.sync_to_aoms(
            tier="episodic",
            payload={"type": "observation", "title": "x", "outcome": "y"},
            silent=False,
        )


@pytest.mark.asyncio
async def test_sync_daily_log_posts_each_section(monkeypatch):
    fake_client = OpenClawFakeClient(
        responses=[FakeResponse(200, {}), FakeResponse(200, {})],
    )
    monkeypatch.setattr(oc.httpx, "AsyncClient", lambda timeout=5.0: fake_client)

    content = "# Daily\n\n## First\nDid one thing\n\n## Second\nDid another thing"
    ok = await oc.sync_daily_log("2026-02-26", content)

    assert ok is True
    assert len(fake_client.posts) == 2
    assert all(url.endswith("/memory/episodic") for url, _ in fake_client.posts)


@pytest.mark.asyncio
async def test_sync_memory_md_writes_to_target(monkeypatch, tmp_path):
    # Create required directory structure
    (tmp_path / "modules/memory").mkdir(parents=True)
    
    # Monkeypatch Path to return our tmp_path as the root
    class FakePath:
        def __init__(self, *args):
            self._path = tmp_path if args and args[0] == "/home/dhawal/cortex-mem/cortex-mem" else tmp_path / "/".join(str(a) for a in args)
        def __truediv__(self, other):
            return tmp_path / other
    
    monkeypatch.setattr(oc, "Path", FakePath)

    ok = await oc.sync_memory_md("# updated memory")
    target = tmp_path / "modules/memory/MEMORY.md"

    assert ok is True
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "# updated memory"


@pytest.mark.asyncio
async def test_is_aoms_available_false_on_exception(monkeypatch):
    fake_client = OpenClawFakeClient(raises=RuntimeError("offline"))
    monkeypatch.setattr(oc.httpx, "AsyncClient", lambda timeout=2.0: fake_client)

    available = await oc.is_aoms_available()

    assert available is False


@pytest.mark.asyncio
async def test_daemon_client_smart_query_and_close(monkeypatch):
    fake_http = DaemonFakeClient()
    monkeypatch.setattr(daemon.httpx, "AsyncClient", lambda timeout=30.0: fake_http)

    client = daemon.AOMemoryClient(base_url="http://example")
    result = await client.smart_query("memory")
    await client.close()

    assert result["id"] == "abc123"
    assert fake_http.posts[0][0].endswith("/cortex/query")
    assert fake_http.closed is True


@pytest.mark.asyncio
async def test_daemon_client_adjust_weight_returns_false_when_api_rejects(monkeypatch):
    fake_http = DaemonFakeClient()
    monkeypatch.setattr(daemon.httpx, "AsyncClient", lambda timeout=30.0: fake_http)

    client = daemon.AOMemoryClient(base_url="http://example")
    ok = await client.adjust_weight(entry_id="x", task_score=0.8)

    assert ok is False


@pytest.mark.asyncio
async def test_log_goal_execution_uses_expected_tags(monkeypatch):
    captured = {}

    class FakeAOMemoryClient:
        async def write_episode(self, episode_type, title, outcome, tags=None, metadata=None):
            captured["episode_type"] = episode_type
            captured["title"] = title
            captured["outcome"] = outcome
            captured["tags"] = tags
            captured["metadata"] = metadata
            return "id-1"

        async def close(self):
            captured["closed"] = True

    monkeypatch.setattr(daemon, "AOMemoryClient", FakeAOMemoryClient)

    await daemon.log_goal_execution(
        goal_name="Ship tests",
        outcome="Done",
        success=True,
        duration_ms=321,
    )

    assert captured["episode_type"] == "achievement"
    assert "success" in captured["tags"]
    assert captured["metadata"]["duration_ms"] == 321
    assert captured["closed"] is True
