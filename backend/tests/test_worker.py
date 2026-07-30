from app.config import Settings
from app.repository import Job
from app.worker import Worker, extract_article_html


def test_readability_extractor_prefers_article_content() -> None:
    html = """
    <html>
      <head><title>雨の日の散歩</title></head>
      <body>
        <nav>広告とメニュー</nav>
        <article>
          <h1>雨の日の散歩</h1>
          <p>雨の日は、ゆっくり歩くのが好きです。</p>
          <p>傘の音を聞きながら、街を見ます。</p>
        </article>
        <footer>Copyright</footer>
      </body>
    </html>
    """

    title, article = extract_article_html(html, "https://example.com/rain")

    assert title == "雨の日の散歩"
    assert "雨の日は、ゆっくり歩くのが好きです。" in article
    assert "広告とメニュー" not in article


class RecordingRepository:
    def __init__(self) -> None:
        self.updated_title: tuple[int, str] | None = None
        self.enqueued: dict | None = None

    def update_material_title(self, material_id: int, title: str) -> None:
        self.updated_title = material_id, title

    def enqueue_job(self, *, kind: str, material_id: int, payload: dict) -> int:
        self.enqueued = {"kind": kind, "material_id": material_id, "payload": payload}
        return 1


def test_url_fetch_uses_page_title_when_user_did_not_provide_one(monkeypatch) -> None:
    repository = RecordingRepository()
    worker = Worker(repository, Settings())
    monkeypatch.setattr("app.worker.extract_article", lambda _: ("雨の日の散歩", "雨です。"))

    worker._fetch(Job(id=1, kind="fetch", material_id=8, payload={"url": "https://example.com"}, attempts=1))

    assert repository.updated_title == (8, "雨の日の散歩")
    assert repository.enqueued == {
        "kind": "tts",
        "material_id": 8,
        "payload": {"text": "雨です。"},
    }


def test_url_fetch_keeps_a_user_supplied_title(monkeypatch) -> None:
    repository = RecordingRepository()
    worker = Worker(repository, Settings())
    monkeypatch.setattr("app.worker.extract_article", lambda _: ("ページの題", "雨です。"))

    worker._fetch(
        Job(
            id=1,
            kind="fetch",
            material_id=8,
            payload={"url": "https://example.com", "title_provided": True},
            attempts=1,
        )
    )

    assert repository.updated_title is None
