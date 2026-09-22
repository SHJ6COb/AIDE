"""The glossary split into topic files must stay whole and stay indexed.

Splitting one file into eleven creates two new ways to lose knowledge
silently: a term can end up in no file, and `CONTEXT.md`'s index can drift
out of step with what the files actually define. Neither raises anything at
runtime -- the agent simply answers a little worse, weeks later, with nothing
to point at. These tests are what makes both loud.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core import knowledge

_CONTEXT = Path(__file__).resolve().parents[1] / "CONTEXT.md"
_TERM = re.compile(r"^\*\*([^*]+)\*\*:\s*$", re.MULTILINE)
"""A term heading is `**Name**:` alone on a line.

`[^*]` rather than `.+?` on purpose: a *sentence* that happens to end in
`**:` -- e.g. one closing with `**observed, not inferred**:` -- otherwise
matches, and the whole sentence gets treated as a glossary term that
`CONTEXT.md` is then required to index. A real term name never contains
markup, so excluding `*` is both correct and the narrower rule.
"""


def _terms(body: str) -> list[str]:
    return _TERM.findall(body)


def test_every_topic_parses_and_declares_a_known_predicate():
    topics = knowledge.topics()

    assert topics, "no topic files found"
    for topic in topics:
        assert topic.summary, f"{topic.slug} has an empty summary"
        assert topic.loads_when in knowledge.KNOWN_PREDICATES
        assert _terms(topic.body), f"{topic.slug} defines no terms"


def test_no_term_is_defined_in_two_topics():
    """A term in two files is a term that will be corrected in one of them."""
    seen: dict[str, str] = {}
    for topic in knowledge.topics():
        for term in _terms(topic.body):
            assert term not in seen, f"{term!r} defined in both {seen[term]} and {topic.slug}"
            seen[term] = topic.slug


def test_context_index_lists_exactly_what_the_topics_define():
    """`CONTEXT.md` is an index, not a copy. It is only useful while it is
    accurate, and nothing else would notice if it went stale."""
    index = _CONTEXT.read_text(encoding="utf-8")

    for topic in knowledge.topics():
        assert f"knowledge/{topic.slug}.md" in index, f"{topic.slug} missing from CONTEXT.md"
        for term in _terms(topic.body):
            assert term in index, f"{term!r} ({topic.slug}) missing from CONTEXT.md"


def test_context_index_holds_no_definitions_of_its_own():
    """The whole point of the index is that there is one copy of the text."""
    assert not _terms(_CONTEXT.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "fact",
    [
        # One load-bearing fact per always-loaded topic -- the split must not
        # have dropped a body while leaving its heading behind.
        "028100944104Y",  # identifiers: SNR13 = MATNR + PACKINDEX
        "PACK_USAGE",  # identifiers: the Sales Channel naming trap
        "Create Second Version",  # determination-record: the two change gestures
        "DETERMINATION",  # determination-record: the master node
        "TOPICSTRING",  # replication-flow
        "Packspec Status",  # packaging-specification
    ],
)
def test_load_all_carries_the_facts_answers_depend_on(fact: str):
    assert fact in knowledge.load_all()


def test_malformed_front_matter_raises_rather_than_loading_empty(tmp_path: Path, monkeypatch):
    """A typo in `loads_when` must fail at import, not match nothing forever."""
    bad = tmp_path / "broken.md"
    bad.write_text(
        "---\nconcept: broken\nsummary: x\nloads_when: whenever_i_feel_like_it\n---\n\n**X**:\ny\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(knowledge, "_KNOWLEDGE_DIR", tmp_path)

    with pytest.raises(ValueError, match="unknown loads_when"):
        knowledge.topics()
