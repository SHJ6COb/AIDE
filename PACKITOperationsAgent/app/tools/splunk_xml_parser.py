"""Pure XML parsing of Splunk's `output_mode=xml` search-results export.

No domain knowledge here — see `transform.py` for turning these raw field
dicts into PackIT-shaped records.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass


class MalformedSplunkResultsError(Exception):
    """Raised when the top-level `<results>` XML itself doesn't parse."""


@dataclass(frozen=True)
class RawResult:
    """One `<result>` row from a Splunk export, field name -> raw value(s).

    `fields` values are `str` for single-valued fields and `list[str]` for
    Splunk's rare multivalued fields (e.g. `_si`). `_raw` is always a `str`.
    """

    fields: dict[str, str | list[str]]

    def get(self, name: str) -> str | list[str] | None:
        return self.fields.get(name)

    def raw(self) -> str:
        value = self.fields.get("_raw", "")
        return value if isinstance(value, str) else ""


def parse_results(xml_text: str) -> list[RawResult]:
    """Parse a Splunk `results` XML export into a list of `RawResult`.

    Two field-encoding shapes exist in Splunk's export and must be handled
    differently:

    - Every field except `_raw` uses `<field k="name"><value><text>...`.
    - `_raw` uses `<field k="_raw"><v xml:space="preserve">...` instead, and
      Splunk splits that content with `<sg>` highlight tags around matched
      search terms. Reading only `<v>`'s `.text` silently truncates at the
      first highlighted term — the fix is `"".join(v.itertext())`, which
      walks all descendant text including inside `<sg>` tags.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise MalformedSplunkResultsError(str(exc)) from exc

    results: list[RawResult] = []
    for result_el in root.findall("result"):
        fields: dict[str, str | list[str]] = {}
        for field_el in result_el.findall("field"):
            name = field_el.get("k")
            if name is None:
                continue
            if name == "_raw":
                v_el = field_el.find("v")
                fields[name] = "".join(v_el.itertext()) if v_el is not None else ""
            else:
                texts = [t.text or "" for t in field_el.findall("value/text")]
                fields[name] = texts[0] if len(texts) == 1 else texts
        results.append(RawResult(fields=fields))
    return results
