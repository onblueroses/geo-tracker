"""Citation parser tests."""

from geo_tracker.parser import extract_domain, parse_citations


def test_extract_domain_strips_www_and_path():
    assert extract_domain("https://www.example.com/some/path?q=1") == "example.com"
    assert extract_domain("http://Docs.Example.Com:8080/") == "docs.example.com"


def test_extract_domain_handles_garbage():
    assert extract_domain("") == ""
    assert extract_domain("not-a-url") == ""
    assert extract_domain(None) == ""  # type: ignore[arg-type]


def test_parse_openrouter_shape():
    raw = {
        "choices": [
            {
                "message": {
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url_citation": {
                                "url": "https://example.com/post",
                                "title": "Example post",
                                "content": "Some snippet",
                            },
                        },
                        {
                            "type": "url_citation",
                            "url_citation": {
                                "url": "https://other.com/x",
                                "title": "Other",
                            },
                        },
                        # duplicate url — should be deduped
                        {
                            "type": "url_citation",
                            "url_citation": {"url": "https://example.com/post"},
                        },
                    ]
                }
            }
        ]
    }
    cites = parse_citations(raw, self_domains={"example.com"})
    assert len(cites) == 2
    assert cites[0].cited_domain == "example.com"
    assert cites[0].is_self is True
    assert cites[0].rank == 1
    assert cites[1].cited_domain == "other.com"
    assert cites[1].is_self is False


def test_parse_empty_response():
    assert parse_citations({}, set()) == []
    assert parse_citations({"choices": []}, set()) == []
    assert parse_citations({"choices": [{"message": {}}]}, set()) == []
