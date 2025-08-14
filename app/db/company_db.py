from dataclasses import dataclass
from typing import List, Optional, Iterable, Tuple, Dict, Any
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "companies.sqlite"

@dataclass
class CompanyRow:
    id: int
    name: str
    machines: str
    skills: str
    notes: str
    capacity: Optional[str] = ""
    location: Optional[str] = ""


def _conn():
    return sqlite3.connect(DB_PATH)


def _has_column(con: sqlite3.Connection, table: str, col: str) -> bool:
    cur = con.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())


def init_db(seed: bool = True):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS companies(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                machines TEXT NOT NULL,
                skills TEXT NOT NULL,
                notes TEXT NOT NULL
            );
            """
        )
        # Optional columns
        if not _has_column(con, "companies", "capacity"):
            con.execute("ALTER TABLE companies ADD COLUMN capacity TEXT DEFAULT ''")
        if not _has_column(con, "companies", "location"):
            con.execute("ALTER TABLE companies ADD COLUMN location TEXT DEFAULT ''")

        # Assignments table
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS assignments(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_name TEXT NOT NULL,
                company_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        # Add drawing_file to assignments if missing
        cur = con.execute("PRAGMA table_info(assignments)").fetchall()
        cols = [r[1] for r in cur]
        if 'drawing_file' not in cols:
            con.execute("ALTER TABLE assignments ADD COLUMN drawing_file TEXT DEFAULT ''")
        if seed and not list(fetch_all()):
            seed_data = [
                ("大田VMC精機", "VMC,三次元測定機", "ステンレス,フランジ", "SUS加工が得意。薄肉注意。", "Medium", "Tokyo"),
                ("町工場フライス", "汎用フライス,ボール盤", "アルミ,プレート", "小ロット歓迎。", "Low", "Kawasaki"),
                ("精密タップ工業", "タッピングセンタ", "SUS,ねじ穴", "ねじ穴加工の実績豊富。", "High", "Yokohama"),
            ]
            con.executemany("INSERT INTO companies(name,machines,skills,notes,capacity,location) VALUES(?,?,?,?,?,?)", seed_data)


def fetch_all() -> List[CompanyRow]:
    with _conn() as con:
        # Ensure columns exist
        if not _has_column(con, "companies", "capacity"):
            con.execute("ALTER TABLE companies ADD COLUMN capacity TEXT DEFAULT ''")
        if not _has_column(con, "companies", "location"):
            con.execute("ALTER TABLE companies ADD COLUMN location TEXT DEFAULT ''")
        rows = con.execute("SELECT id,name,machines,skills,notes,capacity,location FROM companies").fetchall()
    return [CompanyRow(*r) for r in rows]


def fetch_by_id(company_id: int) -> Optional[CompanyRow]:
    with _conn() as con:
        # Ensure optional columns exist
        if not _has_column(con, "companies", "capacity"):
            con.execute("ALTER TABLE companies ADD COLUMN capacity TEXT DEFAULT ''")
        if not _has_column(con, "companies", "location"):
            con.execute("ALTER TABLE companies ADD COLUMN location TEXT DEFAULT ''")
        row = con.execute(
            "SELECT id,name,machines,skills,notes,capacity,location FROM companies WHERE id=?",
            (company_id,),
        ).fetchone()
    return CompanyRow(*row) if row else None


def create_company(
    name: str,
    machines: str,
    skills: str,
    notes: str = "",
    capacity: str = "",
    location: str = "",
) -> int:
    with _conn() as con:
        # Ensure columns exist
        if not _has_column(con, "companies", "capacity"):
            con.execute("ALTER TABLE companies ADD COLUMN capacity TEXT DEFAULT ''")
        if not _has_column(con, "companies", "location"):
            con.execute("ALTER TABLE companies ADD COLUMN location TEXT DEFAULT ''")
        cur = con.execute(
            "INSERT INTO companies(name,machines,skills,notes,capacity,location) VALUES(?,?,?,?,?,?)",
            (name, machines, skills, notes, capacity, location),
        )
        return cur.lastrowid


def update_company(company_id: int, fields: Dict[str, Any]) -> bool:
    allowed = ["name", "machines", "skills", "notes", "capacity", "location"]
    sets = []
    params: List[Any] = []
    for k in allowed:
        if k in fields and fields[k] is not None:
            sets.append(f"{k}=?")
            params.append(str(fields[k]))
    if not sets:
        return False
    params.append(company_id)
    with _conn() as con:
        con.execute(f"UPDATE companies SET {', '.join(sets)} WHERE id=?", params)
        return True


def delete_company(company_id: int) -> bool:
    with _conn() as con:
        con.execute("DELETE FROM companies WHERE id=?", (company_id,))
        return True


def save_assignment(task_name: str, company_id: int, drawing_file: str = "") -> int:
    with _conn() as con:
        # ensure column exists
        curcols = [r[1] for r in con.execute("PRAGMA table_info(assignments)").fetchall()]
        if 'drawing_file' in curcols:
            cur = con.execute(
                "INSERT INTO assignments(task_name, company_id, drawing_file) VALUES(?,?,?)",
                (task_name, company_id, drawing_file or ""),
            )
        else:
            cur = con.execute(
                "INSERT INTO assignments(task_name, company_id) VALUES(?,?)",
                (task_name, company_id),
            )
        return cur.lastrowid


def fetch_assignments() -> List[Tuple[int, str, int, str, str]]:
    with _conn() as con:
        curcols = [r[1] for r in con.execute("PRAGMA table_info(assignments)").fetchall()]
        if 'drawing_file' in curcols:
            rows = con.execute(
                "SELECT id, task_name, company_id, created_at, drawing_file FROM assignments ORDER BY id DESC"
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT id, task_name, company_id, created_at FROM assignments ORDER BY id DESC"
            ).fetchall()
    # normalize to 5-tuple
    norm = []
    for r in rows:
        if len(r) == 5:
            norm.append(r)
        else:
            rid, task_name, company_id, created_at = r
            norm.append((rid, task_name, company_id, created_at, ""))
    return norm

def fetch_assignment_files() -> List[Tuple[str, int]]:
    """Return list of (drawing_file, count) for assignments having a non-empty file."""
    with _conn() as con:
        curcols = [r[1] for r in con.execute("PRAGMA table_info(assignments)").fetchall()]
        if 'drawing_file' not in curcols:
            return []
        rows = con.execute(
            "SELECT drawing_file, COUNT(1) FROM assignments WHERE drawing_file IS NOT NULL AND drawing_file <> '' GROUP BY drawing_file ORDER BY MAX(id) DESC"
        ).fetchall()
    return rows

def fetch_assignments_for_file(drawing_file: str) -> List[Tuple[int, str, int, str, str]]:
    with _conn() as con:
        curcols = [r[1] for r in con.execute("PRAGMA table_info(assignments)").fetchall()]
        if 'drawing_file' in curcols:
            rows = con.execute(
                "SELECT id, task_name, company_id, created_at, drawing_file FROM assignments WHERE drawing_file=? ORDER BY id DESC",
                (drawing_file,),
            ).fetchall()
        else:
            rows = []
    return rows


def search_by_text(q: str) -> List[CompanyRow]:
    q = f"%{q}%"
    with _conn() as con:
        rows = con.execute(
            "SELECT id,name,machines,skills,notes FROM companies WHERE name LIKE ? OR machines LIKE ? OR skills LIKE ? OR notes LIKE ?",
            (q, q, q, q),
        ).fetchall()
    return [CompanyRow(*r) for r in rows]
