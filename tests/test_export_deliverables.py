import scripts.export_deliverables as exp


def test_finds_citations_without_url() -> None:
    citations = [{"citation_id": "cit-1", "url": "https://x"}, {"citation_id": "cit-2", "url": "  "}]
    assert exp.find_missing_urls(citations) == ["cit-2"]


def test_finds_rule_citations_that_do_not_exist() -> None:
    citations = [{"citation_id": "cit-1", "url": "u"}]
    rules = [
        {"rule_id": "a", "citation_ids": "cit-1"},
        {"rule_id": "b", "citation_ids": "cit-1|cit-9"},
        {"rule_id": "c", "citation_ids": ""},
    ]
    assert exp.find_dangling_citations(rules, citations) == {"b": ["cit-9"]}


def test_export_copies_deliverables(tmp_path) -> None:
    exp.export(tmp_path / "out")
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["VERSION", "citations.csv", "rules.csv"]


def test_current_catalog_has_no_dangling_citations() -> None:
    rules = exp.read_rows(exp.CATALOG / "rules.csv")
    citations = exp.read_rows(exp.CATALOG / "citations.csv")
    assert exp.find_dangling_citations(rules, citations) == {}
