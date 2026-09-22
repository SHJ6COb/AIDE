"""The domain glossary, split into topic files that can be loaded selectively.

`CONTEXT.md` used to be pasted whole into every `COMPOSE` and `EXPLAIN` turn:
48 entries, ~11,000 tokens, against a data payload of ~140. Most of it could
not possibly bear on the question being answered -- a stuck-PS question
carried the PSTE entry, the POE->P1M migration, and PSTV integration
mechanics. That is not only cost. Text in context is *material to answer
from*: an unrelated entry sitting in front of the model is an invitation to
mention it, which is where a measurable share of this project's invented
detail came from.

So the glossary is now one file per topic, each declaring in front matter when
it is relevant:

    ---
    concept: activation-counter
    summary: ...
    loads_when: has_superseded_activations
    ---

**Selection is not wired up yet, deliberately.** `load_all()` returns every
topic, which is byte-equivalent in coverage to the old behaviour, so this
split changes no answer. What it buys first is the *structure*: the same
topic files are the unit either mechanism needs -- code-selected loading for
the status path (where the pipeline knows what it found), or retrieval for the
"how does this work" path (where the question is the only signal there is).
Committing to either before the files existed would have been guessing.

`loads_when` values are therefore **declarations of intent, not live
predicates**. `KNOWN_PREDICATES` pins the vocabulary so a typo in a topic file
fails loudly at import rather than silently never matching -- the same reason
`_skill_sections()` raises on a renamed heading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_KNOWLEDGE_DIR = Path(__file__).resolve().parents[1] / "agents" / "packspec_status" / "knowledge"

KNOWN_PREDICATES = frozenset(
    {
        "always",
        "has_superseded_activations",
        "has_multiple_hops",
        "has_target_system",
        "has_dependent_objects",
        "mentions_documents",
        "is_routing_question",
        "mentions_structure",
    }
)
"""Every `loads_when` a topic file may declare.

Each names state the pipeline **already computes for another reason** --
`superseded_count`, `dependent_objects is None`, hop counts, the resolved
target system. That constraint is the point: a predicate invented purely to
select a file is one nothing else exercises, so it can rot silently. One that
the status logic itself depends on cannot -- if it breaks, the status answer
breaks first, and loudly.
"""

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


@dataclass(frozen=True)
class Topic:
    slug: str
    summary: str
    loads_when: str
    body: str

    @property
    def text(self) -> str:
        return self.body.strip() + "\n"


def _parse(path: Path) -> Topic:
    match = _FRONT_MATTER.match(path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"{path.name}: missing or malformed front matter")

    fields: dict[str, str] = {}
    for line in match.group(1).split("\n"):
        key, _, value = line.partition(":")
        if not _:
            raise ValueError(f"{path.name}: front-matter line is not `key: value`: {line!r}")
        fields[key.strip()] = value.strip()

    missing = {"concept", "summary", "loads_when"} - fields.keys()
    if missing:
        raise ValueError(f"{path.name}: front matter missing {sorted(missing)}")
    if fields["concept"] != path.stem:
        raise ValueError(f"{path.name}: concept {fields['concept']!r} does not match filename")
    if fields["loads_when"] not in KNOWN_PREDICATES:
        raise ValueError(
            f"{path.name}: unknown loads_when {fields['loads_when']!r}; "
            f"expected one of {sorted(KNOWN_PREDICATES)}"
        )
    return Topic(fields["concept"], fields["summary"], fields["loads_when"], match.group(2))


def topics() -> list[Topic]:
    """Every topic file, in filename order.

    Raises rather than returning a partial list: a glossary that quietly loses
    a topic degrades answers weeks later with no error to point at.
    """
    found = sorted(_KNOWLEDGE_DIR.glob("*.md"))
    if not found:
        raise ValueError(f"no knowledge topics found under {_KNOWLEDGE_DIR}")
    return [_parse(path) for path in found]


def load_all() -> str:
    """The whole glossary -- what every composing turn gets today.

    Kept as the single call site so switching on selection later is one
    change here, not a search for everywhere the glossary was assembled.
    """
    return "\n\n".join(topic.text for topic in topics())


_QUESTION_PREDICATE_HINTS = {
    "mentions_documents": ("document", "dir ", " dir", "attachment", "drawing"),
    "is_routing_question": ("rout", "reach", "supposed to", "why did", "why didn", "arrive"),
    "mentions_structure": ("level", "element", "structure", "packaging material", "content node", "pstv"),
}
"""Crude keyword hints for the three question-side predicates.

Deliberately crude. Nothing acts on the result (see `firing_predicates`), so a
false positive costs a wrong line in a log and nothing else. Sharpening these
before there is traffic to sharpen them *against* would be guessing.
"""


def firing_predicates(
    question: str,
    *,
    superseded_count: int = 0,
    has_dependent_objects: bool = False,
    target_system_count: int = 0,
    max_hops: int = 0,
) -> frozenset[str]:
    """Which `loads_when` predicates this turn would satisfy, if selection were on.

    **Observation only. Nothing selects on this and nothing may.** Its purpose
    is to answer a question the corpus cannot answer from inspection: how often
    does each predicate actually fire on real traffic? Withholding a topic
    before that is known would be trading a measurable cost (tokens) for an
    unmeasured risk (an answer that needed the topic).

    Two families, and the difference matters. The `has_*` predicates read state
    the pipeline already computed for another reason, which is what keeps them
    honest -- a predicate nothing else exercises can rot silently. The three
    question-side ones have no such backing and are keyword hints only.

    Callers pass primitives rather than pipeline objects on purpose: this module
    is imported by the harness, so taking `StatusResult` here would invert the
    dependency for the sake of instrumentation.
    """
    firing = {"always"}
    if superseded_count > 0:
        firing.add("has_superseded_activations")
    if has_dependent_objects:
        firing.add("has_dependent_objects")
    if target_system_count > 0:
        firing.add("has_target_system")
    if max_hops > 1:
        firing.add("has_multiple_hops")

    lowered = question.lower()
    for predicate, hints in _QUESTION_PREDICATE_HINTS.items():
        if any(hint in lowered for hint in hints):
            firing.add(predicate)

    return frozenset(firing & KNOWN_PREDICATES)
