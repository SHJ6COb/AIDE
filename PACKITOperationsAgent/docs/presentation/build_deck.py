"""Build the PACKIT Operations Agent presentation deck.

Kept as a generator rather than a hand-edited .pptx so the deck can be rebuilt
after the product changes, and so every number in it can be traced to where it
came from. Run:

    python docs/presentation/build_deck.py

Output: docs/presentation/PACKIT_Operations_Agent.pptx
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

OUT = Path(__file__).parent / "PACKIT_Operations_Agent.pptx"

# A restrained, presentation-safe palette. Deliberately not Bosch brand assets --
# swap these for the official ones before an external showing.
INK = RGBColor(0x1A, 0x22, 0x2E)      # near-black body text
MUTED = RGBColor(0x5B, 0x68, 0x7A)    # secondary text
ACCENT = RGBColor(0x00, 0x6E, 0x8A)   # primary accent
ACCENT_2 = RGBColor(0xC1, 0x44, 0x2E)  # problem/alert
GOOD = RGBColor(0x1E, 0x7A, 0x53)     # confirmed / working
SURFACE = RGBColor(0xF2, 0xF5, 0xF7)  # panel fill
LINE = RGBColor(0xD3, 0xDA, 0xE0)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

TITLE_SIZE = Pt(30)
BODY_SIZE = Pt(15)


def _text(frame, runs, *, size=BODY_SIZE, color=INK, bold=False, align=PP_ALIGN.LEFT, space_after=6):
    """Write paragraphs into a text frame. `runs` is a list of strings, or of
    (text, level) tuples for indented bullets."""
    frame.word_wrap = True
    first = True
    for item in runs:
        text, level = item if isinstance(item, tuple) else (item, 0)
        p = frame.paragraphs[0] if first else frame.add_paragraph()
        first = False
        p.level = level
        p.alignment = align
        p.space_after = Pt(space_after)
        run = p.add_run()
        run.text = text
        run.font.size = Pt(size.pt - 1) if level else size
        run.font.color.rgb = MUTED if level else color
        run.font.bold = bold and not level
        run.font.name = "Segoe UI"


def _box(slide, x, y, w, h, *, fill=None, line=None, radius=True):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE, x, y, w, h
    )
    if fill is None:
        shape.fill.background()
    else:
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
        shape.line.width = Pt(1)
    shape.shadow.inherit = False
    return shape


def _label(slide, x, y, w, h, text, *, size=12, color=INK, bold=False, align=PP_ALIGN.CENTER):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.margin_left = tf.margin_right = Emu(0)
    tf.margin_top = tf.margin_bottom = Emu(0)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    _text(tf, [text], size=Pt(size), color=color, bold=bold, align=align, space_after=0)
    return tb


def _node(slide, x, y, w, h, title, subtitle=None, *, fill=SURFACE, edge=LINE, title_color=INK):
    _box(slide, x, y, w, h, fill=fill, line=edge)
    if subtitle:
        _label(slide, x, y + Inches(0.10), w, Inches(0.26), title, size=12, bold=True, color=title_color)
        _label(slide, x, y + Inches(0.36), w, Inches(0.24), subtitle, size=9.5, color=MUTED)
    else:
        _label(slide, x, y, w, h, title, size=12, bold=True, color=title_color)


def _arrow(slide, x, y, w, *, color=ACCENT):
    a = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, x, y, w, Inches(0.16))
    a.fill.solid()
    a.fill.fore_color.rgb = color
    a.line.fill.background()
    a.shadow.inherit = False
    return a


def _slide(prs, title, kicker=None):
    s = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    _box(s, Inches(0.6), Inches(0.52), Inches(0.09), Inches(0.42), fill=ACCENT, radius=False)
    tb = s.shapes.add_textbox(Inches(0.85), Inches(0.42), Inches(11.6), Inches(0.62))
    _text(tb.text_frame, [title], size=TITLE_SIZE, bold=True, space_after=0)
    if kicker:
        kb = s.shapes.add_textbox(Inches(0.85), Inches(1.02), Inches(11.6), Inches(0.34))
        _text(kb.text_frame, [kicker], size=Pt(13), color=MUTED, space_after=0)
    return s


def _footer(prs, s, n):
    tb = s.shapes.add_textbox(Inches(11.0), Inches(6.95), Inches(1.9), Inches(0.3))
    _text(tb.text_frame, [f"{n}"], size=Pt(10), color=MUTED, align=PP_ALIGN.RIGHT, space_after=0)


def build() -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    W = prs.slide_width

    # ---------------------------------------------------------------- 1 title
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _box(s, Emu(0), Emu(0), W, Inches(7.5), fill=RGBColor(0x0E, 0x1B, 0x2A), radius=False)
    _box(s, Inches(0.9), Inches(2.55), Inches(0.12), Inches(1.5), fill=ACCENT, radius=False)
    tb = s.shapes.add_textbox(Inches(1.25), Inches(2.45), Inches(10.5), Inches(1.0))
    _text(tb.text_frame, ["PACKIT Operations Agent"], size=Pt(44), color=WHITE, bold=True, space_after=4)
    tb = s.shapes.add_textbox(Inches(1.25), Inches(3.35), Inches(10.5), Inches(0.9))
    _text(
        tb.text_frame,
        ["Answering “what happened to this Packaging Specification?” from live data — grounded, read-only, and verifiable."],
        size=Pt(17),
        color=RGBColor(0xB9, 0xC6, 0xD2),
        space_after=0,
    )
    tb = s.shapes.add_textbox(Inches(1.25), Inches(4.45), Inches(10.5), Inches(0.4))
    _text(tb.text_frame, ["PACKIT • PDMI • Target Systems"], size=Pt(12), color=RGBColor(0x7E, 0x91, 0xA3), space_after=0)

    # ------------------------------------------------------------- 2 problem
    s = _slide(prs, "The problem", "What answering one question costs today")
    left = Inches(0.85)
    steps = [
        ("1. Find the transfer", "Search Splunk (index pdbb) by PS ID. Results are raw JSON/Atom envelopes, one row per processing hop — a single PS can produce 100+."),
        ("2. Work out what actually happened", "Group hops by Message ID *and* Target System. One PS fans out to several targets with independent outcomes; one Message ID is not one transfer."),
        ("3. Decode the error", "Take the Status Description text to the Docupedia error catalogue and match it by eye against 63 documented rows (57 of them actionable) to find the cause, owner and fix."),
        ("4. Decide whether it should have arrived at all", "Query the Additional Routing plan separately — a PS being Active does not mean this Target System was ever configured to receive it."),
    ]
    y = Inches(1.65)
    for title, body in steps:
        _box(s, left, y, Inches(11.6), Inches(1.02), fill=SURFACE, line=LINE)
        _label(s, left + Inches(0.28), y + Inches(0.12), Inches(4.4), Inches(0.3), title, size=13.5, bold=True, align=PP_ALIGN.LEFT, color=ACCENT)
        tb = s.shapes.add_textbox(left + Inches(0.28), y + Inches(0.42), Inches(11.0), Inches(0.5))
        _text(tb.text_frame, [body], size=Pt(11.5), color=MUTED, space_after=0)
        y += Inches(1.15)
    tb = s.shapes.add_textbox(left, Inches(6.35), Inches(11.6), Inches(0.5))
    _text(
        tb.text_frame,
        ["Four systems, four vocabularies, joined by hand — every time, by whoever happens to be asked."],
        size=Pt(14),
        color=ACCENT_2,
        bold=True,
        space_after=0,
    )

    # ------------------------------------------------------ 3 why it matters
    s = _slide(prs, "Why it matters", "The cost is not only time")
    cards = [
        ("Expertise concentrated", "Only a handful of people can read a raw PDMI payload confidently. They become the bottleneck for everyone else."),
        ("Wrong answers look right", "“Nothing found” and “not found in the last 15 minutes” are different claims. Confusing them sends someone to fix a PS that is fine — or ignore one that is not."),
        ("Knowledge sits in a document", "The error catalogue is real and maintained, but it is only useful if a human remembers to open it and matches the right row."),
    ]
    x = Inches(0.85)
    for title, body in cards:
        _box(s, x, Inches(1.9), Inches(3.75), Inches(2.9), fill=SURFACE, line=LINE)
        _box(s, x, Inches(1.9), Inches(3.75), Inches(0.06), fill=ACCENT_2, radius=False)
        _label(s, x + Inches(0.3), Inches(2.2), Inches(3.2), Inches(0.6), title, size=15, bold=True, align=PP_ALIGN.LEFT)
        tb = s.shapes.add_textbox(x + Inches(0.3), Inches(2.85), Inches(3.2), Inches(1.7))
        _text(tb.text_frame, [body], size=Pt(12), color=MUTED, space_after=0)
        x += Inches(4.0)
    tb = s.shapes.add_textbox(Inches(0.85), Inches(5.25), Inches(11.6), Inches(0.9))
    _text(
        tb.text_frame,
        ["The failure mode that matters most is not “no answer” — it is a confident, plausible, wrong one."],
        size=Pt(16),
        bold=True,
        space_after=0,
    )

    # ------------------------------------------------------------ 4 solution
    s = _slide(prs, "The solution", "A chat interface over the data that already exists")
    _box(s, Inches(0.85), Inches(1.7), Inches(11.6), Inches(1.3), fill=RGBColor(0xE8, 0xF2, 0xF5), line=ACCENT)
    tb = s.shapes.add_textbox(Inches(1.2), Inches(1.95), Inches(11.0), Inches(0.9))
    _text(
        tb.text_frame,
        ["Ask in plain language. It searches Splunk, reconstructs what happened, matches the documented error catalogue, checks the routing plan — and answers with the concrete identifiers you need to act."],
        size=Pt(15),
        space_after=0,
    )
    does = [
        "Names the actual values — SNR13, plant, determination type, target system",
        "Distinguishes source re-publishes from target reprocessing",
        "Reports only the newest activation of a Determination Record",
        "Quotes the documented fix verbatim, including transaction codes and queues",
    ]
    never = [
        "Never triggers, retriggers or edits anything — strictly read-only",
        "Never invents a fix that is not in the error catalogue",
        "Never claims a search it did not run",
        "Never presents an unscoped production sweep as an answer",
    ]
    for title, items, colour, x in (("What it does", does, ACCENT, Inches(0.85)), ("What it never does", never, ACCENT_2, Inches(6.95))):
        _label(s, x, Inches(3.25), Inches(5.5), Inches(0.35), title, size=15, bold=True, align=PP_ALIGN.LEFT, color=colour)
        tb = s.shapes.add_textbox(x, Inches(3.7), Inches(5.5), Inches(2.6))
        _text(tb.text_frame, [f"•  {i}" for i in items], size=Pt(12.5), space_after=10)

    # ------------------------------------------------------------- 5 systems
    s = _slide(prs, "The systems involved", "Four sources, one answer")
    rows = [
        ("PACKIT / PD7", "Source System", "Where a Packaging Specification is created and activated. Publishes a Determination Record per plant / index / supplier."),
        ("PDMI + Solace", "Middleware", "Routes each trigger to the Target System(s) subscribed to its TOPICSTRING."),
        ("Target Systems", "Consumers", "R/3 and S/4-EWM systems that create the Packaging Instruction and BOM. Includes POE (xOE line) and PT0."),
        ("Splunk (pdbb)", "Observability", "Every hop of every transfer, via the Bosch API gateway. The system of record for what actually happened."),
        ("Additional Routing plan", "Configuration", "Which Target System a Plant + Determination Type is configured to reach at all."),
        ("Docupedia error catalogue", "Knowledge", "Documented cause, responsible party and fix per error — the only source the agent may quote a fix from."),
    ]
    y = Inches(1.75)
    for name, kind, body in rows:
        _box(s, Inches(0.85), y, Inches(11.6), Inches(0.78), fill=WHITE, line=LINE)
        _box(s, Inches(0.85), y, Inches(0.06), Inches(0.78), fill=ACCENT, radius=False)
        _label(s, Inches(1.1), y + Inches(0.08), Inches(2.7), Inches(0.3), name, size=12.5, bold=True, align=PP_ALIGN.LEFT)
        _label(s, Inches(1.1), y + Inches(0.40), Inches(2.7), Inches(0.26), kind, size=10, color=MUTED, align=PP_ALIGN.LEFT)
        tb = s.shapes.add_textbox(Inches(4.0), y + Inches(0.16), Inches(8.3), Inches(0.5))
        _text(tb.text_frame, [body], size=Pt(11.5), color=MUTED, space_after=0)
        y += Inches(0.87)

    # --------------------------------------------------------- 6 domain flow
    s = _slide(prs, "How a Packaging Specification reaches a Target System", "The flow the agent has to explain")
    ny, nh = Inches(2.15), Inches(0.95)
    _node(s, Inches(0.85), ny, Inches(2.1), nh, "PACKIT / PD7", "create + activate")
    _arrow(s, Inches(3.05), ny + Inches(0.40), Inches(0.5))
    _node(s, Inches(3.65), ny, Inches(2.1), nh, "PDMI", "publish trigger")
    _arrow(s, Inches(5.85), ny + Inches(0.40), Inches(0.5))
    _node(s, Inches(6.45), ny, Inches(2.1), nh, "Solace", "TOPICSTRING routing")
    _arrow(s, Inches(8.65), ny + Inches(0.40), Inches(0.5))
    _node(s, Inches(9.25), ny, Inches(3.2), nh, "Target Systems", "R/3 · S/4-EWM · POE · PT0", fill=RGBColor(0xE8, 0xF2, 0xF5), edge=ACCENT)

    _box(s, Inches(0.85), Inches(3.55), Inches(11.6), Inches(1.05), fill=SURFACE, line=LINE)
    tb = s.shapes.add_textbox(Inches(1.15), Inches(3.68), Inches(11.0), Inches(0.85))
    _text(
        tb.text_frame,
        [
            "Every hop of this journey is logged to Splunk — that is what the agent reads.",
            "Dependent Objects (Cockpit Master Data, Document Info Records) are sent only to the xOE line, and can block the PS's own transfer until they complete.",
        ],
        size=Pt(12),
        color=MUTED,
        space_after=4,
    )

    facts = [
        ("OBJECTKEY", "identifies the business object — PS ID + SEQNO + activation counter"),
        ("SEQNO", "which Determination Record: one PS can be extended to many plants"),
        ("ZACTCOUNTER", "which version of the PS structure; the target processes the newest"),
    ]
    x = Inches(0.85)
    for name, body in facts:
        _box(s, x, Inches(4.95), Inches(3.75), Inches(1.35), fill=WHITE, line=LINE)
        _label(s, x + Inches(0.25), Inches(5.1), Inches(3.3), Inches(0.3), name, size=12.5, bold=True, align=PP_ALIGN.LEFT, color=ACCENT)
        tb = s.shapes.add_textbox(x + Inches(0.25), Inches(5.45), Inches(3.3), Inches(0.8))
        _text(tb.text_frame, [body], size=Pt(11), color=MUTED, space_after=0)
        x += Inches(4.0)

    # ------------------------------------------------------- 7 architecture
    s = _slide(prs, "Architecture", "What happens between pressing Enter and seeing an answer")
    _node(s, Inches(0.85), Inches(1.75), Inches(1.9), Inches(0.85), "Browser", "React UI")
    _arrow(s, Inches(2.85), Inches(2.10), Inches(0.45))
    _node(s, Inches(3.4), Inches(1.75), Inches(2.1), Inches(0.85), "FastAPI", "SSE streaming")
    _arrow(s, Inches(5.6), Inches(2.10), Inches(0.45))
    _node(s, Inches(6.15), Inches(1.75), Inches(2.4), Inches(0.85), "Turn 1 — LLM", "question → SearchParams", fill=RGBColor(0xF6, 0xEE, 0xE6), edge=RGBColor(0xD8, 0xB9, 0x96))
    _arrow(s, Inches(8.65), Inches(2.10), Inches(0.45))
    _node(s, Inches(9.2), Inches(1.75), Inches(3.25), Inches(0.85), "Deterministic pipeline", "no LLM inside", fill=RGBColor(0xE8, 0xF2, 0xF5), edge=ACCENT)

    _box(s, Inches(0.85), Inches(2.95), Inches(11.6), Inches(1.55), fill=WHITE, line=LINE)
    px = Inches(1.15)
    for i, (step, sub) in enumerate(
        [
            ("Search", "Splunk, 4-call job flow"),
            ("Transform", "hops → Transfers"),
            ("Supersede", "newest activation only"),
            ("Dependent objects", "xOE line only"),
            ("Catalogue", "regex match, no RAG"),
            ("Routing", "only if target missing"),
        ]
    ):
        _node(s, px, Inches(3.15), Inches(1.72), Inches(1.15), step, sub, fill=SURFACE, edge=LINE)
        if i < 5:
            _arrow(s, px + Inches(1.75), Inches(3.65), Inches(0.16), color=LINE)
        px += Inches(1.9)

    _node(s, Inches(3.4), Inches(4.85), Inches(2.6), Inches(0.85), "Turn 2 — LLM", "result → plain answer", fill=RGBColor(0xF6, 0xEE, 0xE6), edge=RGBColor(0xD8, 0xB9, 0x96))
    _arrow(s, Inches(6.1), Inches(5.20), Inches(0.45))
    _node(s, Inches(6.65), Inches(4.85), Inches(2.9), Inches(0.85), "Grounding guard", "code, not prompt", fill=RGBColor(0xE9, 0xF3, 0xEC), edge=GOOD)
    _arrow(s, Inches(9.65), Inches(5.20), Inches(0.45))
    _node(s, Inches(10.2), Inches(4.85), Inches(2.25), Inches(0.85), "Answer", "grounded, cited")

    tb = s.shapes.add_textbox(Inches(0.85), Inches(6.1), Inches(11.6), Inches(0.8))
    _text(
        tb.text_frame,
        ["Exactly two LLM calls and one search per question. No open-ended tool loop — the model decides what to look for and how to say it; it never decides what is true."],
        size=Pt(13),
        color=MUTED,
        space_after=0,
    )

    # -------------------------------------------------------- 8 guardrails
    s = _slide(prs, "Why the answers can be trusted", "The guarantees live in code, not in the prompt")
    guards = [
        ("Scope guard", "A question too broad to search never reaches Splunk — an unscoped sweep of production could return 200 arbitrary records and be presented as relevant."),
        ("Grounding guard", "A fix that is not in the error catalogue is replaced with “no documented fix — raise a ticket”. An empty result can never be answered as though something was found."),
        ("Time-window parser", "The window the user asked for is applied deterministically, not left to the model to remember."),
        ("Activation supersession", "Errors on a replaced version of a PS are excluded — and never in a way that could hide a live failure."),
        ("Target-line gate", "Dependent objects are only looked for where they can exist, so an empty result is never narrated as a problem."),
    ]
    y = Inches(1.75)
    for name, body in guards:
        _box(s, Inches(0.85), y, Inches(11.6), Inches(0.92), fill=WHITE, line=LINE)
        _box(s, Inches(0.85), y, Inches(0.06), Inches(0.92), fill=GOOD, radius=False)
        _label(s, Inches(1.15), y + Inches(0.16), Inches(2.9), Inches(0.3), name, size=13, bold=True, align=PP_ALIGN.LEFT, color=GOOD)
        tb = s.shapes.add_textbox(Inches(4.2), y + Inches(0.14), Inches(8.1), Inches(0.7))
        _text(tb.text_frame, [body], size=Pt(11.5), color=MUTED, space_after=0)
        y += Inches(1.0)

    # --------------------------------------------------------- 9 before/after
    s = _slide(prs, "What changes for the user", "One real question, before and after")
    _label(s, Inches(0.85), Inches(1.6), Inches(5.5), Inches(0.35), "Before", size=15, bold=True, align=PP_ALIGN.LEFT, color=ACCENT_2)
    _box(s, Inches(0.85), Inches(2.0), Inches(5.5), Inches(2.5), fill=RGBColor(0xFA, 0xF0, 0xEE), line=RGBColor(0xE3, 0xBE, 0xB6))
    tb = s.shapes.add_textbox(Inches(1.1), Inches(2.2), Inches(5.0), Inches(2.2))
    _text(
        tb.text_frame,
        [
            "“The SNR13 is not found or marked for deletion.”",
            "“The plant is not specified in the provided data — you may need to check with the appropriate team.”",
        ],
        size=Pt(12.5),
        space_after=10,
    )
    _label(s, Inches(6.95), Inches(1.6), Inches(5.5), Inches(0.35), "After", size=15, bold=True, align=PP_ALIGN.LEFT, color=GOOD)
    _box(s, Inches(6.95), Inches(2.0), Inches(5.5), Inches(2.5), fill=RGBColor(0xEE, 0xF6, 0xF1), line=RGBColor(0xB4, 0xD5, 0xC2))
    tb = s.shapes.add_textbox(Inches(7.2), Inches(2.2), Inches(5.0), Inches(2.2))
    _text(
        tb.text_frame,
        [
            "“PS 00000000040001253724 (plant 0110, SHIP) is in ERROR at SAPP870110 after 100 processing attempts: SNR13 028100944104Y is not found or marked for deletion.”",
            "“Create 028100944104Y on SAPP870110 or remove its deletion flag — Target Error, responsible: Plant.”",
        ],
        size=Pt(12.5),
        space_after=10,
    )
    tb = s.shapes.add_textbox(Inches(0.85), Inches(4.85), Inches(11.6), Inches(1.2))
    _text(
        tb.text_frame,
        [
            "The difference is not tone. The first answer cannot be acted on; the second can be pasted into the target system.",
            "The data was always there — the product simply was not passing it through.",
        ],
        size=Pt(13.5),
        space_after=8,
    )

    # ----------------------------------------------------- 10 verification
    s = _slide(prs, "How we know it works", "A regression suite that can prove a wrong answer")
    _box(s, Inches(0.85), Inches(1.7), Inches(11.6), Inches(1.15), fill=RGBColor(0xE8, 0xF2, 0xF5), line=ACCENT)
    tb = s.shapes.add_textbox(Inches(1.15), Inches(1.85), Inches(11.0), Inches(0.9))
    _text(
        tb.text_frame,
        ["The data sources are frozen from real captures; the app, its HTTP clients and the live model all run for real. Any deviation is therefore the product's, not the backend's — which is the only way an expected result means anything."],
        size=Pt(13),
        space_after=0,
    )
    stats = [
        ("257", "real Splunk events replayed"),
        ("10", "scenarios / 28 conversation turns"),
        ("210", "unit tests"),
        ("Every", "answer traced to the SPL that produced it"),
    ]
    x = Inches(0.85)
    for big, small in stats:
        _box(s, x, Inches(3.15), Inches(2.75), Inches(1.5), fill=WHITE, line=LINE)
        _label(s, x, Inches(3.3), Inches(2.75), Inches(0.7), big, size=30, bold=True, color=ACCENT)
        _label(s, x + Inches(0.2), Inches(4.0), Inches(2.35), Inches(0.5), small, size=10.5, color=MUTED)
        x += Inches(2.95)
    tb = s.shapes.add_textbox(Inches(0.85), Inches(5.0), Inches(11.6), Inches(1.5))
    _text(
        tb.text_frame,
        [
            "It found real defects: a stated time window being silently replaced by a 15-minute default, an answer claiming a window it had not searched, a promise to check a second PS that was never checked, and a documented fix reported as “no documented fix”.",
            "Each is now covered by a test that fails if it returns.",
        ],
        size=Pt(12.5),
        color=MUTED,
        space_after=8,
    )

    # ------------------------------------------------------------- 11 lesson
    s = _slide(prs, "What we learned building it", "Worth carrying into the next agent")
    lessons = [
        ("Guards in code held. Rules in the prompt did not.", "Time windows, continuation promises and identifier fidelity were all governed by instructions alone — and all four failed. Rewriting the instructions moved the numbers barely at all; moving the rule into code fixed it in one pass."),
        ("A prompt rule constrains wording, not belief.", "Told not to promise a second search, the model stopped promising — and started reporting the outcome of a search it never ran. The same false claim, one layer down."),
        ("The domain owner is the source of truth.", "Independent analysis was right about structure and wrong about meaning twice. Both errors would have shipped as confident code."),
    ]
    y = Inches(1.8)
    for title, body in lessons:
        _box(s, Inches(0.85), y, Inches(11.6), Inches(1.42), fill=SURFACE, line=LINE)
        _label(s, Inches(1.2), y + Inches(0.18), Inches(10.9), Inches(0.34), title, size=15, bold=True, align=PP_ALIGN.LEFT, color=ACCENT)
        tb = s.shapes.add_textbox(Inches(1.2), Inches(0.0) + y + Inches(0.6), Inches(10.9), Inches(0.75))
        _text(tb.text_frame, [body], size=Pt(12), color=MUTED, space_after=0)
        y += Inches(1.6)

    # ------------------------------------------------------------- 12 status
    s = _slide(prs, "Status and what is next", None)
    _label(s, Inches(0.85), Inches(1.7), Inches(5.5), Inches(0.35), "Working today", size=15, bold=True, align=PP_ALIGN.LEFT, color=GOOD)
    tb = s.shapes.add_textbox(Inches(0.85), Inches(2.15), Inches(5.5), Inches(3.4))
    _text(
        tb.text_frame,
        [f"•  {t}" for t in [
            "Status, error cause and documented fix for any PS",
            "Multi-target fan-out reported per target",
            "Dependent-object blocking, scoped to the xOE line",
            "Additional Routing check when a target is missing",
            "Domain questions answered from the glossary",
            "Single-process launch, pre-built UI, no Node required",
        ]],
        size=Pt(12.5),
        space_after=9,
    )
    _label(s, Inches(6.95), Inches(1.7), Inches(5.5), Inches(0.35), "Next", size=15, bold=True, align=PP_ALIGN.LEFT, color=ACCENT)
    tb = s.shapes.add_textbox(Inches(6.95), Inches(2.15), Inches(5.5), Inches(3.4))
    _text(
        tb.text_frame,
        [f"•  {t}" for t in [
            "Reuse the last result so follow-ups skip a Splunk round trip",
            "Capture a Document Info Record payload to confirm the PS ↔ DIR link",
            "Surface the interpreted search on screen, so a misreading is visible",
            "Paginate beyond 200 rows — today a very long retry chain is truncated",
            "Widen the regression corpus as new error patterns appear",
        ]],
        size=Pt(12.5),
        space_after=9,
    )
    _box(s, Inches(0.85), Inches(5.75), Inches(11.6), Inches(0.85), fill=RGBColor(0xE8, 0xF2, 0xF5), line=ACCENT)
    _label(s, Inches(1.15), Inches(5.9), Inches(11.0), Inches(0.55), "Read-only by design. It tells you what happened and what the catalogue says to do — a human still does it.", size=13.5, bold=True, align=PP_ALIGN.LEFT)

    for i, sl in enumerate(prs.slides):
        if i:
            _footer(prs, sl, i + 1)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    return OUT


if __name__ == "__main__":
    print(f"written: {build()}")
