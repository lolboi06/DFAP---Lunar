from dfap.ldrm_subsystem.persistence.repositories import SQLiteRepository
import sqlite3
repo = SQLiteRepository('data/ldrm/ldrm.sqlite3')
repo.connection.row_factory = sqlite3.Row
head = repo.connection.execute("SELECT value FROM metadata WHERE key='audit_head'").fetchone()
count = repo.connection.execute("SELECT count(*) FROM audit").fetchone()
print("head:", dict(head) if head else None)
print("count:", dict(count) if count else None)
