# db.py
# Author: Marco D'Amico <marcodamico@protonmail.com>
# Copyright (c) 2026 Marco D'Amico

import sqlite3
import os

DB_PATH = "hashes.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS hashes (
            photo_id TEXT PRIMARY KEY,
            hash TEXT,
            url TEXT,
            title TEXT,
            date_taken TEXT,
            width INTEGER,
            height INTEGER
        )
    ''')
    
    # Check if we need to add width/height columns to an existing table
    cursor.execute("PRAGMA table_info(hashes)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'width' not in columns:
        cursor.execute("ALTER TABLE hashes ADD COLUMN width INTEGER")
    if 'height' not in columns:
        cursor.execute("ALTER TABLE hashes ADD COLUMN height INTEGER")
        
    conn.commit()
    conn.close()

def get_hash(photo_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT hash, url, title, width, height FROM hashes WHERE photo_id = ?', (photo_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_all_hashes():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT photo_id, hash, url, title, width, height FROM hashes')
    rows = cursor.fetchall()
    conn.close()
    # {photo_id: (hash, url, title, width, height)}
    return {row[0]: row[1:] for row in rows}

def get_hash_count():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM hashes')
    count = cursor.fetchone()[0]
    conn.close()
    return count

def save_hash(photo_id, hash_str, url, title, date_taken, width=None, height=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO hashes (photo_id, hash, url, title, date_taken, width, height)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (photo_id, hash_str, url, title, date_taken, width, height))
    conn.commit()
    conn.close()

def delete_hashes(photo_ids):
    if not photo_ids:
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executemany("DELETE FROM hashes WHERE photo_id = ?", [(pid,) for pid in photo_ids])
    conn.commit()
    conn.close()

def clear_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()

init_db()
