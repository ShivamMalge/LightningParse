"""Generate the mixed-page-size fixture for PHASES-MARGIN-BANDS.md Phase 2.

Synthetic, no real content, so it is committed.

Exercises G4's *cross-page coupling*: the old band was a fraction of
`global_max_y`, a single document-wide content extent, so one unusually tall
page shifted the margin band on every other page. No pre-existing fixture had
mixed page sizes, so that half of G4 was never covered by a test.

Layout: 3 US-Letter pages (612x792) plus one deliberately tall page
(612x1200) whose content reaches y=1150. Under the old rule the tall page
alone set the band for all four at 1150*0.90 = 1035 -- far above every Letter
page's content, so nothing on them could ever be tagged. Under per-page
geometry each page bands against its own height.
"""

from pathlib import Path

from reportlab.pdfgen import canvas

OUT = Path(__file__).parent / "fixtures" / "mixed_pagesize.pdf"
LETTER = (612.0, 792.0)
TALL = (612.0, 1200.0)
RUNNING_HEAD = "Mixed Page Size Fixture"


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUT))

    for i, size in enumerate([LETTER, LETTER, TALL, LETTER], start=1):
        w, h = size
        c.setPageSize(size)
        # Running head, positioned in each page's own top margin.
        c.setFont("Helvetica", 9)
        c.drawString(72, h - 42, RUNNING_HEAD)
        # Body content, well clear of both margins.
        c.setFont("Helvetica", 11)
        c.drawString(72, h - 150, f"Body text on page {i} of the mixed-size fixture.")
        c.drawString(72, h - 170, "This line must never be tagged as page furniture.")
        if size == TALL:
            # Reaches high enough to dominate a document-wide content extent.
            c.drawString(72, 1150, "Tall page content near the very top.")
        c.setFont("Helvetica", 9)
        c.drawString(w / 2.0, 40, str(i))
        c.showPage()

    c.save()
    print(f"[ok] wrote {OUT}")


def verify() -> None:
    import pikepdf

    pdf = pikepdf.open(str(OUT))
    heights = []
    for page in pdf.pages:
        mb = [float(v) for v in page.MediaBox]
        heights.append(round(mb[3] - mb[1], 1))
    print(f"[ok] page heights: {heights}")
    assert len(set(heights)) > 1, "fixture must contain more than one page size"


if __name__ == "__main__":
    build()
    verify()
