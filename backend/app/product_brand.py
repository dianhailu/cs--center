"""Per-product branding: agent name, KB scope, PinGo→Avantee text rebrand."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models import Product
from app.rbac import normalize_product

DEFAULT_PINGO_AGENT = "PinGo CS"
DEFAULT_PINGO_PRODUCT = "PinGo"


@dataclass(frozen=True)
class ProductBrand:
    product_code: str
    product_name: str
    agent_display_name: str
    kb_source_product_code: str | None = None
    source_product_name: str = DEFAULT_PINGO_PRODUCT
    source_agent_name: str = DEFAULT_PINGO_AGENT

    @property
    def borrows_kb(self) -> bool:
        src = (self.kb_source_product_code or "").strip().lower()
        return bool(src and src != self.product_code.lower())

    @property
    def uses_own_history(self) -> bool:
        """History pairs are PinGo-only until tagged by product; skip when borrowing KB."""
        return not self.borrows_kb


def brand_from_product(product: Product | None, *, product_code: str) -> ProductBrand:
    code = normalize_product(product_code)
    if not product:
        if code == "avantee":
            return ProductBrand(
                product_code=code,
                product_name="Avantee",
                agent_display_name="Joy",
                kb_source_product_code="pingo",
            )
        return ProductBrand(
            product_code=code,
            product_name=DEFAULT_PINGO_PRODUCT if code == "pingo" else code.title(),
            agent_display_name=DEFAULT_PINGO_AGENT,
        )
    agent = (product.agent_display_name or "").strip() or DEFAULT_PINGO_AGENT
    kb_src = (product.kb_source_product_code or "").strip().lower() or None
    return ProductBrand(
        product_code=code,
        product_name=(product.name or code).strip(),
        agent_display_name=agent,
        kb_source_product_code=kb_src,
    )


def load_product_brand(db: Session, product_code: str) -> ProductBrand:
    code = normalize_product(product_code)
    product = db.get(Product, code)
    return brand_from_product(product, product_code=code)


def _legacy_product_code(item: dict[str, Any]) -> str:
    pc = (item.get("product_code") or "").strip().lower()
    return pc or "pingo"


def rebrand_text(text: str, brand: ProductBrand) -> str:
    if not text or not brand.borrows_kb:
        return text
    out = text
    pairs = [
        (brand.source_agent_name, brand.agent_display_name),
        ("Pin Go CS", brand.agent_display_name),
        (brand.source_product_name, brand.product_name),
        ("Pin Go", brand.product_name),
    ]
    for src, dst in pairs:
        if not src or src == dst:
            continue
        out = re.sub(re.escape(src), dst, out, flags=re.IGNORECASE)
    return out


def rebrand_lang_block(block: dict[str, Any] | None, brand: ProductBrand) -> dict[str, str]:
    if not isinstance(block, dict):
        return {}
    return {k: rebrand_text(str(v or ""), brand) for k, v in block.items()}


def rebrand_faq_item(item: dict[str, Any], brand: ProductBrand) -> dict[str, Any]:
    if not brand.borrows_kb:
        return copy.deepcopy(item)
    out = copy.deepcopy(item)
    out["product_code"] = brand.product_code
    out["question"] = rebrand_lang_block(out.get("question"), brand)
    out["answer"] = rebrand_lang_block(out.get("answer"), brand)
    if out.get("category"):
        out["category"] = rebrand_lang_block(out.get("category"), brand)
    return out


def faq_items_for_brand(items: list[dict[str, Any]], brand: ProductBrand) -> list[dict[str, Any]]:
    own = brand.product_code.lower()
    src = (brand.kb_source_product_code or own).lower()
    out: list[dict[str, Any]] = []
    for raw in items:
        pc = _legacy_product_code(raw)
        if pc == own:
            out.append(copy.deepcopy(raw))
        elif brand.borrows_kb and pc == src:
            out.append(rebrand_faq_item(raw, brand))
    return out


def agent_name_aliases(brand: ProductBrand) -> set[str]:
    names = {
        brand.agent_display_name.strip().lower(),
        brand.product_name.strip().lower(),
        brand.product_code.strip().lower(),
    }
    if brand.borrows_kb:
        # LA may still show legacy PinGo labels in echoed messages during migration.
        names.update({"pingo cs", "pin go cs", "pingo"})
    return {n for n in names if n}
