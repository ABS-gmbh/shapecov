"""Rebuild the derived parts of the corpus.

  corpus_build.py [corpus dir]

For each manifest entry:
  * a generated entry is re-encoded from its value file with tools/encode.py;
  * sha256, size_bytes, cells and cells_new_in_protocol are recomputed from
    the bytes with the independent decoder and the two schema versions.
Hand-written fields (title, caps, shape, expected, source, sightings) are left
alone. Run tools/corpus_check.py afterwards.
"""
import base64
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from decode import Decoder  # noqa: E402
from encode import Encoder  # noqa: E402
from gen import all_cells  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main():
    corpus = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "corpus"
    schema = json.load(open(ROOT / "schema/schema.json"))
    prev = json.load(open(ROOT / "schema/schema-v28.0.json"))
    new_cells = all_cells(schema) - all_cells(prev)
    dec, enc = Decoder(schema), Encoder(schema)
    mpath = corpus / "manifest.json"
    manifest = json.load(open(mpath))
    for e in manifest["entries"]:
        f = corpus / e["file"]
        if e["source"]["kind"] == "generated":
            value = json.load(open(corpus / e["source"]["value_file"]))
            f.write_text(base64.b64encode(enc.encode(e["xdr_type"], value)).decode() + "\n")
        raw = base64.b64decode(f.read_text().strip(), validate=True)
        dec.decode(e["xdr_type"], raw)
        e["sha256"] = hashlib.sha256(raw).hexdigest()
        e["size_bytes"] = len(raw)
        e["cells"] = sorted(dec.cells)
        e["cells_new_in_protocol"] = sorted(set(dec.cells) & new_cells)
        print(f"{e['id']}: {len(raw)} bytes, {len(e['cells'])} cells, "
              f"{len(e['cells_new_in_protocol'])} new in protocol {manifest['xdr_schema']['protocol_version']}")
    mpath.write_text(json.dumps(manifest, indent=1) + "\n")


if __name__ == "__main__":
    main()
