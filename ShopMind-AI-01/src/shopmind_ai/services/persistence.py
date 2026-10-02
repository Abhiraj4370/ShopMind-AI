"""Lightweight persistent storage for ShopMind.

Uses SQLite by default so the project works locally without requiring a
PostgreSQL server. The schema is intentionally portable and can later be
mapped to PostgreSQL without changing the API contract.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import hashlib
import hmac
import secrets
import base64
import time
from pathlib import Path
from typing import Any


class PersistenceStore:
    def __init__(self, path: str | None = None) -> None:
        default = os.getenv("SHOPMIND_DB_PATH", "data/shopmind.db")
        self.path = Path(path or default)
        if not self.path.is_absolute():
            self.path = Path.cwd() / self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                session_id TEXT,
                query TEXT NOT NULL,
                country_code TEXT,
                currency TEXT,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL,
                product_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                UNIQUE(fingerprint, created_at)
            );
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL,
                url TEXT,
                name TEXT NOT NULL,
                merchant TEXT NOT NULL,
                price REAL NOT NULL,
                currency TEXT NOT NULL,
                captured_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_price_history_fp ON price_history(fingerprint, captured_at);
            CREATE TABLE IF NOT EXISTS wishlist (
                user_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                product_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY(user_id, fingerprint)
            );
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                product_json TEXT NOT NULL,
                target_price REAL,
                currency TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                last_price REAL,
                triggered INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            """)
            try:
                self._conn.execute("ALTER TABLE alerts ADD COLUMN triggered INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass

    @staticmethod
    def fingerprint(product: dict[str, Any]) -> str:
        url = str(product.get("url") or "").strip().lower()
        merchant = str(product.get("merchant_id") or product.get("merchant_name") or "").lower()
        pid = str(product.get("product_id") or "").lower()
        return "|".join((merchant, pid, url))

    def record_search(self, user_id: str, session_id: str, query: str, country: str, currency: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO searches(user_id,session_id,query,country_code,currency,created_at) VALUES(?,?,?,?,?,?)",
                (user_id, session_id, query, country, currency, time.time()),
            )

    def save_products(self, products: list[dict[str, Any]]) -> None:
        now = time.time()
        with self._lock, self._conn:
            for product in products:
                fp = self.fingerprint(product)
                self._conn.execute(
                    "INSERT INTO products(fingerprint,product_json,created_at) VALUES(?,?,?)",
                    (fp, json.dumps(product, default=str), now),
                )
                price = product.get("display_price")
                currency = product.get("display_currency") or product.get("currency")
                if price is not None and currency:
                    self._conn.execute(
                        "INSERT INTO price_history(fingerprint,url,name,merchant,price,currency,captured_at) VALUES(?,?,?,?,?,?,?)",
                        (fp, product.get("url", ""), product.get("name", ""), product.get("merchant_name", ""), float(price), currency, now),
                    )

    def price_history(self, fingerprint: str, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT price,currency,captured_at FROM price_history WHERE fingerprint=? ORDER BY captured_at DESC LIMIT ?",
                (fingerprint, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def wishlist_add(self, user_id: str, product: dict[str, Any]) -> None:
        fp = self.fingerprint(product)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO wishlist(user_id,fingerprint,product_json,created_at) VALUES(?,?,?,?)",
                (user_id, fp, json.dumps(product, default=str), time.time()),
            )

    def wishlist_remove(self, user_id: str, fingerprint: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM wishlist WHERE user_id=? AND fingerprint=?", (user_id, fingerprint))

    def wishlist(self, user_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT product_json FROM wishlist WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def alert_add(self, user_id: str, product: dict[str, Any], target_price: float | None) -> int:
        fp = self.fingerprint(product)
        currency = product.get("display_currency") or product.get("currency")
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO alerts(user_id,fingerprint,product_json,target_price,currency,active,last_price,triggered,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (user_id, fp, json.dumps(product, default=str), target_price, currency, 1, product.get("display_price"), 0, time.time()),
            )
            return int(cur.lastrowid)

    def alerts(self, user_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if user_id:
                rows = self._conn.execute("SELECT * FROM alerts WHERE user_id=? ORDER BY updated_at DESC", (user_id,)).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM alerts WHERE active=1 ORDER BY updated_at DESC").fetchall()
        return [dict(row) for row in rows]

    def update_alert(self, alert_id: int, last_price: float | None, active: bool | None = None, triggered: bool | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE alerts SET last_price=?,active=COALESCE(?,active),triggered=COALESCE(?,triggered),updated_at=? WHERE id=?",
                (last_price, None if active is None else int(active), None if triggered is None else int(triggered), time.time(), alert_id),
            )

    @staticmethod
    def hash_password(password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
        return base64.urlsafe_b64encode(salt + digest).decode()

    @staticmethod
    def verify_password(password: str, encoded: str) -> bool:
        try:
            raw = base64.urlsafe_b64decode(encoded.encode())
            salt, expected = raw[:16], raw[16:]
            actual = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
            return hmac.compare_digest(actual, expected)
        except Exception:
            return False

    def create_user(self, email: str, password: str) -> str:
        user_id = secrets.token_urlsafe(18)
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(?,?,?,?)", (user_id, email.lower().strip(), self.hash_password(password), time.time()))
        return user_id

    def authenticate_user(self, email: str, password: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT id,password_hash FROM users WHERE email=?", (email.lower().strip(),)).fetchone()
        if not row or not self.verify_password(password, row["password_hash"]):
            return None
        return str(row["id"])

    def user_by_id(self, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT id,email,created_at FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def stats(self) -> dict[str, Any]:
        with self._lock:
            searches = self._conn.execute("SELECT COUNT(*) FROM searches").fetchone()[0]
            products = self._conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            wishlist = self._conn.execute("SELECT COUNT(*) FROM wishlist").fetchone()[0]
            alerts = self._conn.execute("SELECT COUNT(*) FROM alerts WHERE active=1").fetchone()[0]
            top = self._conn.execute("SELECT query,COUNT(*) c FROM searches GROUP BY query ORDER BY c DESC LIMIT 10").fetchall()
        return {"searches": searches, "products_recorded": products, "wishlist_items": wishlist, "active_alerts": alerts, "popular_searches": [dict(r) for r in top]}

    def event(self, event_type: str, payload: dict[str, Any]) -> None:
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO events(event_type,payload_json,created_at) VALUES(?,?,?)", (event_type, json.dumps(payload, default=str), time.time()))
