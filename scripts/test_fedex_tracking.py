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

from tracker.fedex import fetch_tracking_result, summarize_track_result


def main() -> None:
    parser = argparse.ArgumentParser(description='Proof-of-life FedEx tracking lookup for FedExSucks FS1')
    parser.add_argument('--tracking-number', default=os.getenv('FEDEX_TRACKING_NUMBER'))
    parser.add_argument('--raw', action='store_true', help='Print full raw JSON response')
    args = parser.parse_args()

    if not args.tracking_number:
        raise SystemExit('Provide --tracking-number or set FEDEX_TRACKING_NUMBER in .env')

    payload, result = fetch_tracking_result(args.tracking_number)

    if args.raw:
        print(json.dumps(payload, indent=2))
        return

    print(json.dumps(summarize_track_result(result), indent=2, default=str))


if __name__ == '__main__':
    try:
        main()
    except requests.RequestException as exc:
        print(f'Network/request failure: {exc}', file=sys.stderr)
        raise SystemExit(1)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
