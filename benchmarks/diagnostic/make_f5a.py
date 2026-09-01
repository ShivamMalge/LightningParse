"""Generate F5a — the synthetic /PageLabels control fixture for docs/NEW_PHASES.md Phase 1.

F5a is deliberately synthetic and committed: it contains no real textbook content,
so it is exempt from the real-content-stays-out-of-the-repo rule in docs/NEW_PHASES.md.

Structure (20 pages):
  PDF index 1..6   front matter, printed labels i..vi   (roman lowercase)
  PDF index 7..20  body,         printed labels 1..14   (arabic, RESTARTED at 1)

The offset between PDF index and printed label is therefore NOT constant:
  front matter: printed = pdf_index      (as roman)
  body:         printed = pdf_index - 6

Two independent carriers of the printed label are present, on purpose:
  1. a /PageLabels number tree in the catalog  (machine-readable metadata)
  2. the label rendered as ink in a centered footer  (what a human reads)
This lets Phase 1 distinguish "ignores the metadata" from "cannot see the label
at all". Body pages also carry a constant running header, which is a genuine
running head that is NOT the page label — Phase 2 needs that separation to score
header/footer precision without conflating the two.

Anchor tokens are opaque (ANCHOR-F5A-07), encoding only the PDF index and never
the printed label, so that a label harvester reading body text cannot accidentally
score correct.
"""

import sys
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent / "fixtures" / "f5a_pagelabels.pdf"

PAGE_W, PAGE_H = letter
FRONT_MATTER_PAGES = 6
BODY_PAGES = 14
TOTAL = FRONT_MATTER_PAGES + BODY_PAGES

RUNNING_HEAD = "The Human Eye"

FRONT_MATTER = [
    ("Structures of the Human Eye", ["A Synthetic Fixture for Parser Diagnostics"]),
    ("Copyright", ["This document is synthetic. It contains no real textbook content."]),
    ("Dedication", ["For anyone who has ever cited the wrong page."]),
    ("Contents", ["Chapter 1  The Human Eye . . . . . . . 1"]),
    ("Preface", ["Front matter is numbered separately from the body."]),
    ("Preface, continued", ["The body restarts at arabic 1 on the seventh PDF page."]),
]

BODY = [
    ("The Human Eye", "The cornea is the transparent front layer of the eye."),
    ("The Cornea", "Corneal curvature accounts for most of the eye's refractive power."),
    ("The Iris", "The iris controls the diameter of the pupil."),
    ("The Pupil", "Pupil diameter varies with ambient light intensity."),
    ("The Lens", "The crystalline lens fine-tunes focus through accommodation."),
    ("Accommodation", "Ciliary muscles change lens shape to focus on near objects."),
    ("The Vitreous Humour", "The vitreous humour maintains intraocular pressure."),
    ("The Retina", "The retina converts incident light into neural signals."),
    ("Rods and Cones", "Rods handle low light; cones handle colour discrimination."),
    ("The Fovea", "The fovea contains the highest density of cone cells."),
    ("The Optic Disc", "The optic disc contains no photoreceptors, creating a blind spot."),
    ("The Optic Nerve", "The optic nerve carries signals from retina to visual cortex."),
    ("Visual Pathways", "Signals cross at the optic chiasm before reaching the thalamus."),
    ("Summary", "Each structure contributes to forming a focused retinal image."),
]

ROMAN = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]


def printed_label(pdf_index: int) -> str:
    """Ground truth: the label a human reads on the page at this 1-based PDF index."""
    if pdf_index <= FRONT_MATTER_PAGES:
        return ROMAN[pdf_index - 1]
    return str(pdf_index - FRONT_MATTER_PAGES)


def draw_footer(c: canvas.Canvas, label: str) -> None:
    """Bare centered label — the most common real textbook form."""
    c.setFont("Helvetica", 10)
    c.drawCentredString(PAGE_W / 2.0, 40, label)


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUT), pagesize=letter)

    for i in range(1, TOTAL + 1):
        if i <= FRONT_MATTER_PAGES:
            title, body_lines = FRONT_MATTER[i - 1]
            c.setFont("Helvetica-Bold", 18)
            c.drawString(72, 700, title)
            c.setFont("Helvetica", 11)
            y = 660
            for line in body_lines:
                c.drawString(72, y, line)
                y -= 18
        else:
            heading, sentence = BODY[i - FRONT_MATTER_PAGES - 1]
            # Constant running head: a genuine running head that is NOT the label.
            c.setFont("Helvetica-Oblique", 9)
            c.drawString(72, 750, RUNNING_HEAD)
            c.setFont("Helvetica-Bold", 14)
            c.drawString(72, 700, heading)
            c.setFont("Helvetica", 11)
            y = 670
            for _ in range(3):
                c.drawString(72, y, sentence)
                y -= 18

        # Opaque anchor: encodes the PDF index only, never the printed label.
        c.setFont("Helvetica", 9)
        c.drawString(72, 120, f"ANCHOR-F5A-{i:02d}")

        draw_footer(c, printed_label(i))
        c.showPage()

    c.save()
    print(f"[ok] wrote {TOTAL}-page base PDF -> {OUT}")


def add_page_labels() -> None:
    """Attach the /PageLabels number tree: roman from index 0, decimal restarting at index 6."""
    import pikepdf

    pdf = pikepdf.open(str(OUT), allow_overwriting_input=True)
    pdf.Root.PageLabels = pdf.make_indirect(
        pikepdf.Dictionary(
            Nums=pikepdf.Array(
                [
                    0,
                    pikepdf.Dictionary(S=pikepdf.Name.r),          # lowercase roman
                    FRONT_MATTER_PAGES,
                    pikepdf.Dictionary(S=pikepdf.Name.D, St=1),    # decimal, restart at 1
                ]
            )
        )
    )
    pdf.save(str(OUT) + ".tmp")
    Path(str(OUT) + ".tmp").replace(OUT)
    print("[ok] attached /PageLabels number tree")


def verify() -> None:
    """Confirm the tree is really in the saved file, independently of how we wrote it."""
    import pikepdf

    pdf = pikepdf.open(str(OUT))
    assert "/PageLabels" in pdf.Root, "PageLabels missing from catalog"
    assert len(pdf.pages) == TOTAL, f"expected {TOTAL} pages, got {len(pdf.pages)}"
    print(f"[ok] verified: {len(pdf.pages)} pages, /PageLabels present")
    print("     ground truth (pdf_index -> printed_label):")
    mapping = ", ".join(f"{i}->{printed_label(i)}" for i in range(1, TOTAL + 1))
    print(f"     {mapping}")


if __name__ == "__main__":
    build()
    add_page_labels()
    verify()
    sys.exit(0)
