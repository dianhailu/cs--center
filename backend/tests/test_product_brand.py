from __future__ import annotations

from app.product_brand import ProductBrand, faq_items_for_brand, rebrand_text


def test_rebrand_pingo_to_avantee() -> None:
    brand = ProductBrand(
        product_code="avantee",
        product_name="Avantee",
        agent_display_name="Joy",
        kb_source_product_code="pingo",
    )
    text = "Halo! Terima kasih sudah menghubungi PinGo CS. PinGo adalah platform pinjaman."
    out = rebrand_text(text, brand)
    assert "PinGo" not in out
    assert "Avantee" in out
    assert "Joy" in out


def test_faq_borrow_excludes_other_products() -> None:
    brand = ProductBrand(
        product_code="avantee",
        product_name="Avantee",
        agent_display_name="Joy",
        kb_source_product_code="pingo",
    )
    items = [
        {"id": 1, "product_code": "pingo", "question": {"id": "Apa itu PinGo?"}, "answer": {"id": "PinGo app."}},
        {"id": 2, "product_code": "pingo", "question": {"id": "q"}, "answer": {"id": "a"}},
    ]
    out = faq_items_for_brand(items, brand)
    assert len(out) == 2
    assert out[0]["product_code"] == "avantee"
    assert "Avantee" in out[0]["question"]["id"]
    assert "PinGo" not in out[0]["question"]["id"]


def test_pingo_does_not_see_avantee_faq() -> None:
    brand = ProductBrand(product_code="pingo", product_name="PinGo", agent_display_name="PinGo CS")
    items = [
        {"id": 1, "product_code": "pingo", "question": {"id": "q1"}, "answer": {"id": "a1"}},
        {"id": 2, "product_code": "avantee", "question": {"id": "q2"}, "answer": {"id": "a2"}},
    ]
    out = faq_items_for_brand(items, brand)
    assert len(out) == 1
    assert out[0]["id"] == 1
