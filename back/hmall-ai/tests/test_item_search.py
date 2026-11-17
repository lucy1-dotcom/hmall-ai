"""商品语义搜索的单元测试（不依赖 Milvus / 网络 / 真实 embedding）。

覆盖点：
1. 检索结果能映射出前端渲染商品卡片需要的字段（价格、图片、类目…）
2. 空值元数据不返回，避免前端拿到一堆 null
3. min_score 能过滤低相关度结果
4. embedding 失败要转成 VectorStoreUnavailable，让路由降级
5. 分页拉商品的参数正确
6. 入库时的文本拼接规则
"""

from __future__ import annotations

import pytest

from app.crud.milvus import VectorStoreUnavailable
from app.services import vector_store as vs_module
from app.services.item_client import ItemClient
from app.services.vector_store import VectorStoreService
from ingest_items import build_text


@pytest.fixture(autouse=True)
def _clear_query_cache():
    """查询向量缓存是进程级的，测试之间要清掉，否则会串。"""
    vs_module._QUERY_VECTOR_CACHE.clear()
    yield
    vs_module._QUERY_VECTOR_CACHE.clear()


class FakeRepo:
    """假的 Milvus 仓库：只记录参数、返回预置行。"""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.output_fields = None
        self.filter_expr = None

    def search(self, vector, top_k=10, *, filter_expr=None, output_fields=None):
        self.output_fields = output_fields
        self.filter_expr = filter_expr
        return self.rows


def _service(rows: list[dict], monkeypatch) -> tuple[VectorStoreService, FakeRepo]:
    repo = FakeRepo(rows)
    service = VectorStoreService(repo=repo)
    # 避开真实网络：embedding 直接返回等长零向量，FakeRepo 不关心内容
    monkeypatch.setattr(service, "embed", lambda texts: [[0.0] * 1024 for _ in texts])
    return service, repo


def test_search_returns_item_card_fields(monkeypatch):
    rows = [
        {
            "id": "2120808",
            "item_id": "2120808",
            "name": "华为 FreeBuds 5",
            "text": "华为 FreeBuds 5 华为 耳机 白色",
            "price": 999,
            "image": "/img/2120808.jpg",
            "category": "耳机",
            "brand": "华为",
            "stock": 120,
            "score": 0.87,
        }
    ]
    service, repo = _service(rows, monkeypatch)

    hits = service.search("降噪耳机", top_k=5)

    assert len(hits) == 1
    assert hits[0].item_id == "2120808"
    assert hits[0].name == "华为 FreeBuds 5"
    assert hits[0].score == 0.87
    assert hits[0].metadata == {
        "price": 999,
        "image": "/img/2120808.jpg",
        "category": "耳机",
        "brand": "华为",
        "stock": 120,
    }
    # 必须显式向 Milvus 要这些字段，否则动态字段不会被返回
    assert "price" in repo.output_fields


def test_search_drops_empty_metadata(monkeypatch):
    rows = [
        {
            "id": "1",
            "item_id": "1",
            "name": "无品牌商品",
            "text": "无品牌商品",
            "price": 0,
            "image": "",
            "brand": None,
            "stock": 0,
            "score": 0.6,
        }
    ]
    service, _ = _service(rows, monkeypatch)

    hits = service.search("商品")

    assert hits[0].metadata == {}


def test_min_score_filters_low_similarity(monkeypatch):
    rows = [
        {"id": "1", "item_id": "1", "name": "a", "text": "a", "score": 0.8},
        {"id": "2", "item_id": "2", "name": "b", "text": "b", "score": 0.2},
    ]
    service, _ = _service(rows, monkeypatch)

    hits = service.search("随便搜", min_score=0.5)

    assert [h.item_id for h in hits] == ["1"]


def test_filter_expr_is_built_from_dict(monkeypatch):
    service, repo = _service([], monkeypatch)

    service.search("耳机", filters={"brand": "华为", "stock": 10})

    assert repo.filter_expr == 'brand == "华为" and stock == 10'


def test_embedding_failure_becomes_unavailable(monkeypatch):
    service = VectorStoreService(repo=FakeRepo([]))

    def boom(_texts):
        raise VectorStoreUnavailable("未配置 SILICONFLOW_API_KEY")

    monkeypatch.setattr(service, "embed", boom)

    with pytest.raises(VectorStoreUnavailable):
        service.search("耳机")


def test_item_client_page_params(monkeypatch):
    captured: dict = {}

    def fake_get(path, params=None):
        captured["path"] = path
        captured["params"] = params
        return {"total": 88000, "pages": 880, "list": [{"id": 1}]}

    client = ItemClient("http://gateway:8080")
    monkeypatch.setattr(client, "_get", fake_get)

    page = client.list_items_page(2, 50)

    assert captured["path"] == "/items/page"
    assert captured["params"] == {"pageNo": 2, "pageSize": 50}
    assert page["total"] == 88000


def test_query_vector_is_cached(monkeypatch):
    """同一句话只调一次 embedding——热门搜索词重复率高，这是最划算的优化。"""
    calls: list[list[str]] = []
    service = VectorStoreService(repo=FakeRepo([]))
    monkeypatch.setattr(service, "embed", lambda texts: (calls.append(texts), [[0.1] * 4])[1])

    service.query_vector("降噪耳机")
    service.query_vector("降噪耳机")
    service.query_vector("  降噪耳机  ")

    assert len(calls) == 1


def test_build_text_joins_attributes():
    text = build_text({"name": "华为 FreeBuds 5", "brand": "华为", "category": "耳机", "spec": "白色"})
    assert text == "华为 FreeBuds 5 华为 耳机 白色"


def test_build_text_skips_empty_and_truncates():
    assert build_text({"name": "", "brand": None}) == ""
    assert len(build_text({"name": "长" * 400})) == 300
    # spec 是 JSON 字符串，空规格存的是 "{}"，不能拼进检索文本
    assert build_text({"name": "手机", "category": "手机", "spec": "{}"}) == "手机 手机"
    assert build_text({"name": "手机", "spec": '{"颜色": "黑色"}'}) == '手机 {"颜色": "黑色"}'
