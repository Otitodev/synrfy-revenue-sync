"""
Category mapper: translates VenueSuite product component/category values into
MEWS service identifiers using a YAML configuration file.

Lookup order (most to least specific):
  1. "{component}:{category}"  — compound key (e.g. "extra:av")
  2. "{component}"             — component-only key (e.g. "extra")
  3. "fallback"                — always present; logs a WARNING when used

A missing or unmapped category NEVER causes the sync to fail — it posts using
the fallback and emits a WARNING so operators can update the mapping file.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

from app.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class CategoryMapping:
    display_name: str
    mews_service_id: str
    mews_accounting_category_id: Optional[str]


class CategoryMapper:
    def __init__(self, mapping_path: Optional[str] = None) -> None:
        path = Path(mapping_path or get_settings().category_mapping_path)
        if not path.exists():
            raise FileNotFoundError(f"Category mapping file not found: {path}")
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        self._mappings: dict[str, CategoryMapping] = {}
        for key, entry in raw.get("mappings", {}).items():
            self._mappings[str(key).lower()] = _parse_entry(entry)

        fallback_raw = raw.get("fallback")
        if not fallback_raw:
            raise ValueError("category_mapping.yaml must contain a 'fallback' entry")
        self._fallback = _parse_entry(fallback_raw)

    def resolve(self, component: str, category: str) -> CategoryMapping:
        """
        Return the CategoryMapping for this (component, category) pair.
        Emits WARNING if fallback is used.
        """
        compound_key = f"{component}:{category}".lower()
        component_key = component.lower()

        if compound_key in self._mappings:
            return self._mappings[compound_key]

        if component_key in self._mappings:
            return self._mappings[component_key]

        logger.warning(
            "Unmapped VenueSuite category: component='%s', category='%s'. "
            "Using fallback '%s'. Add this combination to category_mapping.yaml "
            "to suppress this warning.",
            component,
            category,
            self._fallback.display_name,
        )
        return self._fallback


def _parse_entry(entry: dict) -> CategoryMapping:
    return CategoryMapping(
        display_name=entry.get("display_name", ""),
        mews_service_id=entry["mews_service_id"],
        mews_accounting_category_id=entry.get("mews_accounting_category_id"),
    )


@lru_cache(maxsize=1)
def get_category_mapper() -> CategoryMapper:
    return CategoryMapper()
