"""Generate multistream_test.pdf — a page whose /Contents is an array of two
content streams joined at an adversarial boundary.

Stream A ends with `ET` and stream B begins with `BT`, with no whitespace on
either side of the join. Naive concatenation yields the corrupt token `ETBT`;
lopdf >= 0.42 inserts a newline between streams, yielding `ET\nBT`.

Streams are left uncompressed so the fixture stays readable in diffs.
"""

import io

STREAM_A = b"BT /F1 12 Tf 50 700 Td (Alpha from stream one) Tj ET"
STREAM_B = b"BT /F1 12 Tf 50 650 Td (Beta from stream two) Tj ET"


def stream_obj(payload: bytes) -> bytes:
    return b"<</Length " + str(len(payload)).encode() + b">>stream\n" + payload + b"\nendstream"


def main() -> None:
    objs = {
        1: b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
        2: b"<</Font<</F1 1 0 R>>>>",
        3: stream_obj(STREAM_A),
        4: b"<</Type/Page/MediaBox[0 0 612 792]/Contents[3 0 R 7 0 R]"
           b"/Resources 2 0 R/Parent 5 0 R>>",
        5: b"<</Type/Pages/Kids[4 0 R]/Count 1>>",
        6: b"<</Type/Catalog/Pages 5 0 R>>",
        7: stream_obj(STREAM_B),
    }

    out = io.BytesIO()
    out.write(b"%PDF-1.5\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = out.tell()
        out.write(str(num).encode() + b" 0 obj\n" + objs[num] + b"\nendobj\n")

    xref_pos = out.tell()
    out.write(b"xref\n0 " + str(len(objs) + 1).encode() + b"\n")
    out.write(b"0000000000 65535 f \n")
    for num in sorted(objs):
        out.write(("%010d 00000 n \n" % offsets[num]).encode())
    out.write(
        b"trailer\n<</Size " + str(len(objs) + 1).encode() + b"/Root 6 0 R>>\n"
        b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF\n"
    )

    with open("benchmarks/corpus/multistream_test.pdf", "wb") as fh:
        fh.write(out.getvalue())
    print("wrote benchmarks/corpus/multistream_test.pdf")


if __name__ == "__main__":
    main()
