from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import requests

from .fedex import env

PAYROLL_TAX_API_BASE = 'https://payrolltaxapi.com'


class PayrollTaxConfigurationError(RuntimeError):
    pass


class PayrollTaxLookupError(RuntimeError):
    pass


def _clean_value(value: str | None) -> str:
    return (value or '').strip()


def _parse_decimal(value: str | None, *, field_name: str) -> str | None:
    cleaned = _clean_value(value)
    if not cleaned:
        return None
    try:
        return format(Decimal(cleaned), 'f')
    except (InvalidOperation, ValueError) as exc:
        raise PayrollTaxLookupError(f'{field_name} must be a valid number.') from exc


def build_lookup_params(form_data: dict[str, Any]) -> dict[str, str]:
    work_state = _clean_value(form_data.get('workState'))
    pay_date = _clean_value(form_data.get('payDate'))
    if not work_state:
        raise PayrollTaxLookupError('Work state is required.')
    if not pay_date:
        raise PayrollTaxLookupError('Pay date is required.')

    params: dict[str, str] = {
        'workState': work_state.upper(),
        'payDate': pay_date,
        'filingStatus': _clean_value(form_data.get('filingStatus')) or 'single',
    }

    optional_fields = {
        'residenceState': _clean_value(form_data.get('residenceState')).upper(),
        'payPeriod': _clean_value(form_data.get('payPeriod')),
        'allowances': _clean_value(form_data.get('allowances')),
    }
    for key, value in optional_fields.items():
        if value:
            params[key] = value

    gross_wages = _parse_decimal(form_data.get('grossWages'), field_name='Gross wages')
    if gross_wages is not None:
        params['grossWages'] = gross_wages

    ytd_wages = _parse_decimal(form_data.get('ytdWages'), field_name='YTD wages')
    if ytd_wages is not None:
        params['ytdWages'] = ytd_wages

    return params


def lookup_payroll_taxes(form_data: dict[str, Any]) -> dict[str, Any]:
    api_key = env('PAYROLL_TAX_API_KEY', required=False, default='') or ''
    if not api_key:
        raise PayrollTaxConfigurationError('Missing PAYROLL_TAX_API_KEY in environment.')

    params = build_lookup_params(form_data)
    response = requests.get(
        f'{PAYROLL_TAX_API_BASE}/v1/rates/lookup',
        params=params,
        headers={'Authorization': f'Bearer {api_key}'},
        timeout=30,
    )

    if response.status_code >= 400:
        try:
            payload = response.json()
        except Exception:
            payload = {}
        message = payload.get('message') or payload.get('error') or response.text or 'Payroll tax lookup failed.'
        raise PayrollTaxLookupError(message)

    payload = response.json()
    payload['_request_params'] = params
    return payload
