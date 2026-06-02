#!/usr/bin/env python3
import argparse
import hashlib
import json
import random
import sqlite3
from pathlib import Path

try:
    from faker import Faker
except ImportError as exc:
    raise SystemExit("faker is required. Install with: pip install Faker") from exc

fake = Faker('en_US')

SENSITIVE_KEYS = {
    'Shipper name': 'person',
    'Shipper company': 'company',
    'Shipper address': 'address',
    'Shipper city': 'city',
    'Shipper state': 'state',
    'Shipper postal': 'postal',
    'Recipient contact name': 'person',
    'Recipient company': 'company',
    'Recipient address': 'address',
    'Recipient city': 'city',
    'Recipient state': 'state',
    'Recipient postal': 'postal',
    'Received by': 'person',
    'Account number': 'digits',
    'Shipped by': 'company',
    'Shipped to': 'company',
}

TOP_LEVEL_FIELDS = {
    'nickname': 'company',
    'latest_location': 'city_state',
    'notes': 'status_line',
}


def stable_seed(*parts):
    joined = '|'.join(str(p or '') for p in parts)
    return int(hashlib.sha256(joined.encode('utf-8')).hexdigest()[:16], 16)


def seeded_fake(kind, seed_text):
    rng = random.Random(stable_seed(kind, seed_text))
    fake.seed_instance(rng.randint(1, 10**9))
    if kind == 'person':
        return fake.name()
    if kind == 'company':
        return fake.company()
    if kind == 'address':
        return fake.street_address().replace('\n', ', ')
    if kind == 'city':
        return fake.city().upper()
    if kind == 'state':
        return fake.state_abbr()
    if kind == 'postal':
        return fake.postcode()
    if kind == 'digits':
        length = max(6, min(12, len(str(seed_text or ''))))
        return ''.join(rng.choice('0123456789') for _ in range(length))
    if kind == 'city_state':
        return f"{fake.city().upper()}, {fake.state_abbr()}"
    if kind == 'status_line':
        return 'Anonymized shipment notes.'
    return fake.word()


def anonymize_payload(raw_payload, package_id):
    if not raw_payload:
        return raw_payload
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return raw_payload

    row = payload.get('row') or {}
    imported = payload.get('imported_csv_row') or {}

    for key, kind in SENSITIVE_KEYS.items():
        source_value = row.get(key) or imported.get(key) or f'{package_id}:{key}'
        fake_value = seeded_fake(kind, source_value)
        if key in row:
            row[key] = fake_value
        if key in imported:
            imported[key] = fake_value

    payload['row'] = row
    payload['imported_csv_row'] = imported
    return json.dumps(payload, ensure_ascii=False)


def anonymize_db(db_path, dry_run=False, limit=None):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, nickname, latest_location, notes, last_raw_payload FROM tracker_package ORDER BY id")
    rows = cur.fetchall()
    if limit:
        rows = rows[:limit]

    updates = []
    for package_id, nickname, latest_location, notes, raw_payload in rows:
        new_nickname = seeded_fake('company', nickname or f'nickname:{package_id}') if nickname else nickname
        new_location = seeded_fake('city_state', latest_location or f'location:{package_id}') if latest_location else latest_location
        new_notes = seeded_fake('status_line', notes or f'notes:{package_id}') if notes else notes
        new_payload = anonymize_payload(raw_payload, package_id)
        updates.append((new_nickname, new_location, new_notes, new_payload, package_id))

    if dry_run:
        print(f'Dry run: would update {len(updates)} tracker_package rows in {db_path}')
        if updates:
            print('Sample update tuple:', updates[0][:4], '... id=', updates[0][4])
        conn.close()
        return

    cur.executemany(
        """
        UPDATE tracker_package
        SET nickname = ?,
            latest_location = ?,
            notes = ?,
            last_raw_payload = ?
        WHERE id = ?
        """,
        updates,
    )
    conn.commit()
    conn.close()
    print(f'Updated {len(updates)} tracker_package rows in {db_path}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Anonymize tracker_package PII in sqlite db.')
    parser.add_argument('--db', default='db.sqlite3', help='Path to sqlite database')
    parser.add_argument('--dry-run', action='store_true', help='Preview only, do not write changes')
    parser.add_argument('--limit', type=int, default=None, help='Only process first N rows')
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f'Database not found: {db_path}')
    anonymize_db(db_path, dry_run=args.dry_run, limit=args.limit)
