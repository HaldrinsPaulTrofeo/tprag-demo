"""Shared barangay choices for request intake, accounts, and planner."""
import unicodedata

from database import get_db_connection


def norm_barangay(name):
    """Accent-, case- and spacing-insensitive key: 'BIÑAN' and 'Binan' match."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.casefold().split())

BARANGAYS = [
    "Anibong", "Binan", "Buboy", "Cabanbanan", "Calusiche", "Dingin",
    "Lambac", "Layugan", "Magdapio", "Maulawin", "Pinagsanjan",
    "Poblacion Dos", "Poblacion Uno", "Sabang", "Sampaloc", "San Isidro",
]

def barangay_choices():
    known = {name.casefold(): name for name in BARANGAYS}
    extra = []
    conn = get_db_connection()
    if conn is not None:
        try:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT barangay FROM vaccination_sessions")
            for row in cur.fetchall():
                name = row.get("barangay") if isinstance(row, dict) else row[0]
                if name and name.casefold() not in known:
                    known[name.casefold()] = name
                    extra.append(name)
            cur.close()
        except Exception:
            pass  # Canonical choices still work before historical data is loaded.
        finally:
            conn.close()
    return {"barangays": sorted(known.values(), key=str.casefold),
            "canonical": BARANGAYS, "unrecognised": sorted(extra, key=str.casefold)}

def canonical_barangay(value):
    names = {n.casefold(): n for n in barangay_choices()["barangays"]}
    found = names.get(value.strip().casefold())
    if found is None:
        raise ValueError("Choose a barangay from the provided list.")
    return found
