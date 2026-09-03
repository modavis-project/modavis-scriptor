"""Advisory retrieval. Search keys are never written back into a transcription."""
import json
import re
import sqlite3
import unicodedata
from pathlib import Path

from rapidfuzz import fuzz, process

ROOT = Path(__file__).parent


def search_key(text):
    # Deliberately preserve accents, vowels and historical spelling distinctions.
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def label_name(text):
    # Retrieval-only separation of a trailing pitch/rank; original label is retained.
    return re.sub(r"\s+(?:\d[\d\s/.,⅓⅔½]*[′'’\"]?(?:\s*Fuss\.?)?|[IVX]+(?:[-–][IVX]+)?(?:\s*fach)?)$", "", text.strip(), flags=re.I).strip()


class Catalogue:
    def __init__(self, path=ROOT / "corpus/catalogue.sqlite"):
        self.path = path
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            self.labels = {row[0]: row[1] for row in db.execute("SELECT id, search_key FROM labels")}
            self.report = json.loads(db.execute("SELECT value FROM metadata WHERE key='report'").fetchone()[0])

    def match(self, name, limit=5, threshold=65):
        key = search_key(name)
        if len(key) < 3:
            return []
        found = process.extract(key, self.labels, scorer=fuzz.ratio, limit=limit, score_cutoff=threshold)
        with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            results = []
            for _, score, entry_id in found:
                row = dict(db.execute("SELECT * FROM labels WHERE id=?", (entry_id,)).fetchone())
                row["evidence"] = json.loads(row.pop("evidence_json"))
                row["similarity"] = round(score / 100, 4)
                row["relation"] = "attestation" if row["search_key"] == key else "alternative"
                row["warning"] = "Lexical similarity is not identification, correctness probability or permission to replace."
                results.append(row)
        return results
