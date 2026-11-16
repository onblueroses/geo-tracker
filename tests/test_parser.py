"""Citation parser and self-domain normalization."""

from geo_tracker.parser import extract_domain, normalize_self_domains, parse_citations


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
                            "url_citation": {"url": "https://other.com/x", "title": "Other"},
                        },
                        # duplicate url: deduped
                        {"type": "url_citation", "url_citation": {"url": "https://example.com/post"}},
                        # other annotation types: skipped
                        {"type": "file", "file": {"name": "x"}},
                        "not-a-dict",
                    ]
                }
            }
        ]
    }
    cites = parse_citations(raw, self_domains={"example.com"})
    assert [(c.cited_domain, c.rank, c.is_self) for c in cites] == [
        ("example.com", 1, True),
        ("other.com", 2, False),
    ]
    assert cites[0].snippet == "Some snippet"
    assert cites[1].snippet == "Other"


def test_parse_truncates_snippet():
    raw = {"choices": [{"message": {"annotations": [
        {"type": "url_citation", "url_citation": {"url": "https://a.com", "content": "x" * 900}}
    ]}}]}
    assert len(parse_citations(raw, set())[0].snippet or "") == 500


def test_parse_empty_response():
    assert parse_citations({}, set()) == []
    assert parse_citations({"choices": []}, set()) == []
    assert parse_citations({"choices": [{"message": {}}]}, set()) == []


def test_self_domain_normalization_preserves_words_starting_with_w():
    """Regression: `.lstrip("www.")` ate the 'w', 'a', 'l' from "walmart.com"."""
    norm = normalize_self_domains(
        ["walmart.com", "webflow.com", "www2.example.com", "www.example.com"]
    )
    assert norm == {"walmart.com", "webflow.com", "www2.example.com", "example.com"}


def test_self_domain_normalization_accepts_full_urls():
    norm = normalize_self_domains(["https://docs.example.com/api", "http://www.example.com", "  "])
    assert norm == {"docs.example.com", "example.com"}
