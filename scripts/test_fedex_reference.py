#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from tracker.fedex import fetch_reference_tracking_results, summarize_track_result


def main() -> None:
    parser = argparse.ArgumentParser(description='Proof-of-life FedEx reference lookup for FedExSucks FS7')
    parser.add_argument('--reference', default=os.getenv('FEDEX_CUSTOMER_REFERENCE'))
    parser.add_argument('--account-number', default=os.getenv('FEDEX_ACCOUNT_NUMBER'))
    parser.add_argument('--reference-type', default='CUSTOMER_REFERENCE')
    parser.add_argument('--raw', action='store_true')
    args = parser.parse_args()

    if not args.reference:
        raise SystemExit('Provide --reference or set FEDEX_CUSTOMER_REFERENCE in .env')
    if not args.account_number:
        raise SystemExit('Provide --account-number or set FEDEX_ACCOUNT_NUMBER in .env')

    payload, results = fetch_reference_tracking_results(
        reference_value=args.reference,
        account_number=args.account_number,
        reference_type=args.reference_type,
    )

    if args.raw:
        print(json.dumps(payload, indent=2))
        return

    print(json.dumps([summarize_track_result(result) for result in results], indent=2, default=str))


if __name__ == '__main__':
    try:
        main()
    except requests.RequestException as exc:
        print(f'Network/request failure: {exc}', file=sys.stderr)
        raise SystemExit(1)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
