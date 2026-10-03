"""Non-destructive schema reconciliation for request intake.
Default is report-only. Run with --apply to create/upgrade the two tables.
DDL implicitly commits in MySQL; inspect the report and keep a database backup.
"""
import argparse
import re
from database import get_db_connection

CATEGORIES = ("ANTI_RABIES", "LIVESTOCK", "SEEDS", "FINGERLINGS", "INPUTS", "OTHER")
STATUSES = ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "PARTIALLY_APPROVED",
            "DEFERRED", "DECLINED", "FULFILLED")

def enum_type(values):
    return "ENUM(" + ",".join("'" + v + "'" for v in values) + ")"

EXPECTED = {
    "request_id": "BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY",
    "barangay": "VARCHAR(64) NOT NULL",
    "category": enum_type(CATEGORIES) + " NOT NULL DEFAULT 'ANTI_RABIES'",
    "item": "VARCHAR(120) NULL",
    "unit": "VARCHAR(24) NOT NULL DEFAULT 'vials'",
    "qty_requested": "INT NOT NULL",
    "qty_recommended": "INT NULL",
    "qty_granted": "INT NULL",
    "animals_estimated": "INT NULL",
    "households_estimated": "INT NULL",
    "requested_by": "VARCHAR(120) NULL",
    "contact_no": "VARCHAR(40) NULL",
    "request_date": "DATE NOT NULL",
    "needed_by": "DATE NULL",
    "status": enum_type(STATUSES) + " NOT NULL DEFAULT 'SUBMITTED'",
    "decided_by": "VARCHAR(80) NULL",
    "decided_at": "DATETIME NULL",
    "decision_note": "VARCHAR(512) NULL",
    "session_id": "BIGINT NULL",
    "source": "VARCHAR(40) NOT NULL DEFAULT 'online'",
    "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    # Snapshot records the inputs behind the saved recommendation, not just a number.
    "recommendation_json": "LONGTEXT NULL",
    "recommended_at": "DATETIME NULL",
    "decision_history_json": "LONGTEXT NULL",
    # Signatory snapshots, frozen when signed so later profile edits never alter
    # an issued document. Signatures are SHA-256 keys into the signature store.
    "requester_name": "VARCHAR(150) NULL",
    "requester_position": "VARCHAR(150) NULL",
    "requester_signature": "CHAR(64) NULL",
    "requester_seal": "CHAR(64) NULL",
    "requester_signed_at": "DATETIME NULL",
    "approver_name": "VARCHAR(150) NULL",
    "approver_position": "VARCHAR(150) NULL",
    "approver_signature": "CHAR(64) NULL",
    "approver_signed_at": "DATETIME NULL",
}
EXPECTED_TYPES = {"category": CATEGORIES, "status": STATUSES}
INDEXES = {"idx_brgy": "barangay", "idx_status": "status", "idx_date": "request_date"}

def cell(row, key, index=0):
    return row.get(key) if isinstance(row, dict) else row[index]

def enum_values(definition):
    if not definition.lower().startswith("enum("):
        return None
    return re.findall(r"'([^']*)'", definition)

def migration_plan(cur):
    cur.execute("SELECT COLUMN_NAME, COLUMN_TYPE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='service_requests'")
    have = {cell(r, "COLUMN_NAME"): cell(r, "COLUMN_TYPE", 1) for r in cur.fetchall()}
    actions, errors = [], []
    if not have:
        columns = ", ".join(" `" + k + "` " + v for k, v in EXPECTED.items())
        indexes = ", ".join("KEY " + k + " (" + v + ")" for k, v in INDEXES.items())
        actions.append("CREATE TABLE service_requests (" + columns + ", " + indexes +
                       ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
    else:
        cur.execute("SELECT COUNT(*) AS n FROM service_requests")
        populated = int(cell(cur.fetchone(), "n")) > 0
        for name, ddl in EXPECTED.items():
            if name not in have:
                if populated and (name == "request_id" or
                                  ("NOT NULL" in ddl and "DEFAULT" not in ddl)):
                    errors.append(f"Cannot infer {name} for existing requests. Backfill explicitly.")
                else:
                    actions.append(f"ALTER TABLE service_requests ADD COLUMN `{name}` {ddl}")
        for name, target in EXPECTED_TYPES.items():
            if name not in have:
                continue
            old = enum_values(have[name])
            if old is None:
                errors.append(f"{name} is not ENUM; manual data review required.")
            elif not set(old).issubset(target):
                errors.append(f"Refusing to remove existing {name} ENUM values: {old}.")
            elif list(old) != list(target):
                actions.append(f"ALTER TABLE service_requests MODIFY COLUMN `{name}` {EXPECTED[name]}")
        cur.execute("SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='service_requests'")
        indexes = {cell(r, "INDEX_NAME") for r in cur.fetchall()}
        for name, col in INDEXES.items():
            if name not in indexes:
                actions.append(f"ALTER TABLE service_requests ADD INDEX {name} ({col})")

    cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='staff_users'")
    users = {cell(r, "COLUMN_NAME") for r in cur.fetchall()}
    if not users:
        from auth import _CREATE_TABLE
        actions.append(_CREATE_TABLE)
    else:
        if "role" not in users:
            actions.append("ALTER TABLE staff_users ADD COLUMN role VARCHAR(30) DEFAULT 'staff'")
        if "barangay" not in users:
            actions.append("ALTER TABLE staff_users ADD COLUMN barangay VARCHAR(64) NULL")
    return actions, errors

def run(apply=False):
    conn = get_db_connection()
    if conn is None:
        raise RuntimeError("Database unavailable; request migration was not applied.")
    try:
        cur = conn.cursor()
        actions, errors = migration_plan(cur)
        if errors:
            raise RuntimeError("Migration refused: " + " ".join(errors))
        if apply:
            for statement in actions:
                cur.execute(statement)
            conn.commit()
        cur.close()
        return actions
    finally:
        conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        changes = run(args.apply)
        print("\n".join(changes) if changes else "Schema is current.")
        print(f"{len(changes)} changes {'applied' if args.apply else 'planned (report only)'}.")
    except RuntimeError as exc:
        parser.exit(1, str(exc) + "\n")
