from lumina.extensions.repository_catalog import _catalog_tags


def test_catalog_tags_normalize_hashes_duplicates_and_limits() -> None:
    assert _catalog_tags([" #경영기획 ", "디자인", "디자인", "보고서", "초과"]) == [
        "경영기획",
        "디자인",
        "보고서",
    ]
    assert _catalog_tags("디자인") == []
