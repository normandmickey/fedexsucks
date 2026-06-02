import csv
from io import StringIO
from datetime import date, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from .fedex import env, fetch_tracking_result, first_result, load_local_env
from .models import Package, SavedReference
from .payroll_tax import PayrollTaxConfigurationError, PayrollTaxLookupError, lookup_payroll_taxes
from .research import ResearchConfigurationError, run_research
from .services import lookup_and_store_packages, upsert_package_from_result
from .weather import WeatherLookupError, fetch_weather

load_local_env()


def flatten_strings(value):
    if value is None:
        return []
    if isinstance(value, dict):
        parts = []
        for key, child in value.items():
            parts.append(str(key))
            parts.extend(flatten_strings(child))
        return parts
    if isinstance(value, (list, tuple, set)):
        parts = []
        for child in value:
            parts.extend(flatten_strings(child))
        return parts
    return [str(value)]


def package_search_blob(package: Package) -> str:
    parts = [
        package.tracking_number,
        package.nickname,
        package.status,
        package.status_code,
        package.latest_location,
        package.estimated_delivery,
        package.notes,
    ]
    parts.extend(flatten_strings(package.last_raw_payload or {}))
    for event in package.events.all()[:20]:
        parts.extend([
            event.status,
            event.status_code,
            event.location,
            event.details,
        ])
        parts.extend(flatten_strings(event.raw_payload or {}))
    return ' '.join(part for part in parts if part).lower()


def parse_date_input(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def package_in_date_range(package: Package, from_date: date | None, to_date: date | None) -> bool:
    if not from_date and not to_date:
        return True
    if not package.latest_event_at:
        return False
    event_date = package.latest_event_at.date()
    if from_date and event_date < from_date:
        return False
    if to_date and event_date > to_date:
        return False
    return True


def build_package_ui_snapshot(package: Package, query: str = '') -> dict:
    result = first_result(package.last_raw_payload or {}) or {}
    package_details = result.get('packageDetails') or {}
    shipment_details = {
        'package_count': result.get('packageCount'),
        'multi_piece_shipment': result.get('multiPieceShipment'),
        'standard_transit_time_window': result.get('standardTransitTimeWindow'),
        'delivery_details': result.get('deliveryDetails') or {},
        'date_and_times': result.get('dateAndTimes') or [],
        'available_images': result.get('availableImages') or [],
        'service_detail': result.get('serviceDetail') or {},
    }
    payload = package.last_raw_payload or {}
    raw_row = (payload.get('imported_csv_row') or payload.get('row') or {})
    client_search_fields = [
        raw_row.get('Recipient contact name', ''),
        raw_row.get('Recipient company', ''),
        raw_row.get('Recipient address', ''),
        raw_row.get('Recipient city', ''),
        raw_row.get('Recipient state', ''),
        raw_row.get('Recipient postal', ''),
        raw_row.get('Shipper name', ''),
        raw_row.get('Shipper company', ''),
        raw_row.get('Shipper address', ''),
        raw_row.get('Shipper city', ''),
        raw_row.get('Shipper state', ''),
        raw_row.get('Shipper postal', ''),
        raw_row.get('Delivered To', ''),
        raw_row.get('Received by', ''),
        raw_row.get('Reference', ''),
    ]
    client_search_blob = ' '.join(part for part in client_search_fields if part).lower()
    search_blob = f"{package_search_blob(package)} {client_search_blob}".strip()
    query_lower = query.lower().strip()
    shipper_address_parts = [
        raw_row.get('Shipper name', ''),
        raw_row.get('Shipper company', ''),
        raw_row.get('Shipper address', ''),
        raw_row.get('Shipper city', ''),
        raw_row.get('Shipper state', ''),
        raw_row.get('Shipper postal', ''),
        raw_row.get('Shipper country/territory', ''),
    ]
    recipient_address_parts = [
        raw_row.get('Recipient contact name', ''),
        raw_row.get('Recipient company', ''),
        raw_row.get('Recipient address', ''),
        raw_row.get('Recipient city', ''),
        raw_row.get('Recipient state', ''),
        raw_row.get('Recipient postal', ''),
        raw_row.get('Recipient country/territory', ''),
    ]
    recipient_contact = raw_row.get('Recipient contact name', '')
    recipient_company = raw_row.get('Recipient company', '')
    recipient_address_summary_parts = [
        raw_row.get('Recipient address', ''),
        raw_row.get('Recipient city', ''),
        raw_row.get('Recipient state', ''),
        raw_row.get('Recipient postal', ''),
    ]
    ship_date = raw_row.get('Ship date', '')
    delivered_date = raw_row.get('Delivered date', '')
    return {
        'package': package,
        'package_details': package_details,
        'shipment_details': shipment_details,
        'events': list(package.events.all()[:5]),
        'client_search_fields': client_search_fields,
        'shipper_address_lines': [part for part in shipper_address_parts if part],
        'recipient_address_lines': [part for part in recipient_address_parts if part],
        'recipient_contact': recipient_contact,
        'recipient_company': recipient_company,
        'recipient_address_summary': ', '.join(part for part in recipient_address_summary_parts if part),
        'ship_date': ship_date,
        'delivered_date': delivered_date,
        'matches_query': bool(query_lower and query_lower in search_blob),
    }


def build_package_cards(packages, query=''):
    return [build_package_ui_snapshot(package, query=query) for package in packages]


def validate_lookup_dates(ship_date_begin: str | None, ship_date_end: str | None) -> tuple[str | None, str | None, str | None]:
    begin = parse_date_input(ship_date_begin or '')
    end = parse_date_input(ship_date_end or '')
    if not begin or not end:
        return ship_date_begin, ship_date_end, 'Ship date begin and end are required and must be valid dates.'
    if end < begin:
        return ship_date_begin, ship_date_end, 'Ship date end must be on or after ship date begin.'
    if (end - begin).days > 14:
        return ship_date_begin, ship_date_end, 'Keep the ship date window at 14 days or less for now.'
    return begin.isoformat(), end.isoformat(), None


@login_required
def package_detail(request: HttpRequest, tracking_number: str) -> HttpResponse:
    try:
        package = Package.objects.prefetch_related('events').get(tracking_number=tracking_number)
    except Package.DoesNotExist as exc:
        raise Http404('Package not found') from exc

    if request.method == 'POST' and (request.POST.get('action') or '').strip() == 'refresh_tracking':
        try:
            payload, result = fetch_tracking_result(tracking_number)
            imported_csv_row = (package.last_raw_payload or {}).get('imported_csv_row')
            if imported_csv_row:
                payload['imported_csv_row'] = imported_csv_row
            package = upsert_package_from_result(result, payload, nickname=package.nickname)
            messages.success(request, f'Refreshed {tracking_number} from FedEx.')
        except Exception as exc:
            messages.error(request, f'FedEx refresh failed for {tracking_number}: {exc}')
        package = Package.objects.prefetch_related('events').get(tracking_number=tracking_number)

    card = build_package_ui_snapshot(package)
    return render(request, 'tracker/package_detail.html', {
        'card': card,
        'package': package,
    })


@login_required
def research(request: HttpRequest) -> HttpResponse:
    topic = (request.POST.get('topic') or request.GET.get('topic') or '').strip()
    report = ''
    sources: list[str] = []

    if request.method == 'POST':
        if not topic:
            messages.error(request, 'Enter a research topic.')
        else:
            try:
                result = run_research(topic)
                topic = result.topic
                report = result.report
                sources = result.sources
                messages.success(request, f"Research complete for '{topic}'.")
            except ResearchConfigurationError as exc:
                messages.error(request, str(exc))
            except Exception as exc:
                messages.error(request, f'Research failed: {exc}')

    return render(request, 'tracker/research.html', {
        'topic': topic,
        'report': report,
        'sources': sources,
    })


@login_required
def payroll_tax_lookup(request: HttpRequest) -> HttpResponse:
    form_values = {
        'workState': (request.POST.get('workState') or 'CA').strip(),
        'payDate': (request.POST.get('payDate') or date.today().isoformat()).strip(),
        'residenceState': (request.POST.get('residenceState') or '').strip(),
        'filingStatus': (request.POST.get('filingStatus') or 'single').strip(),
        'grossWages': (request.POST.get('grossWages') or '1000').strip(),
        'ytdWages': (request.POST.get('ytdWages') or '').strip(),
        'payPeriod': (request.POST.get('payPeriod') or 'biweekly').strip(),
        'allowances': (request.POST.get('allowances') or '').strip(),
    }
    lookup_payload = None
    taxes = []
    request_params = None

    if request.method == 'POST':
        try:
            lookup_payload = lookup_payroll_taxes(form_values)
            taxes = lookup_payload.get('taxes', []) or []
            request_params = lookup_payload.get('_request_params') or {}
            messages.success(request, f"Loaded {len(taxes)} tax rows.")
        except PayrollTaxConfigurationError as exc:
            messages.error(request, str(exc))
        except PayrollTaxLookupError as exc:
            messages.error(request, str(exc))
        except Exception as exc:
            messages.error(request, f'Payroll tax lookup failed: {exc}')

    return render(request, 'tracker/payroll_tax.html', {
        'form_values': form_values,
        'lookup_payload': lookup_payload,
        'taxes': taxes,
        'request_params': request_params,
        'pay_period_choices': ['weekly', 'biweekly', 'semimonthly', 'monthly', 'annual'],
        'filing_status_choices': ['single', 'married', 'head_of_household'],
    })


@login_required
def weather_forecast(request: HttpRequest) -> HttpResponse:
    location = (request.GET.get('location') or 'New York').strip() or 'New York'
    forecast = None
    try:
        forecast = fetch_weather(location)
    except WeatherLookupError as exc:
        messages.error(request, str(exc))
    except Exception as exc:
        messages.error(request, f'Weather lookup failed: {exc}')

    return render(request, 'tracker/weather.html', {
        'location': location,
        'forecast': forecast,
    })


@login_required
def home(request: HttpRequest) -> HttpResponse:
    query = (request.GET.get('q') or '').strip()
    from_date_raw = (request.GET.get('from') or '').strip()
    to_date_raw = (request.GET.get('to') or '').strip()
    status_view = (request.GET.get('view') or 'active').strip().lower()
    if status_view not in {'active', 'delivered', 'all'}:
        status_view = 'active'
    from_date = parse_date_input(from_date_raw)
    to_date = parse_date_input(to_date_raw)
    lookup_results = []
    lookup_mode = ''
    lookup_text = ''
    lookup_reference_label = ''
    lookup_summary = None

    if request.method == 'POST':
        action = (request.POST.get('action') or 'lookup').strip()

        if action == 'import_csv':
            upload = request.FILES.get('shipping_csv')
            if not upload:
                messages.error(request, 'Choose a CSV file to import.')
            else:
                suffix = Path(upload.name or 'shipping-history.csv').suffix or '.csv'
                with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    for chunk in upload.chunks():
                        tmp.write(chunk)
                    temp_path = tmp.name
                try:
                    with open(temp_path, newline='', encoding='utf-8-sig') as handle:
                        reader = csv.DictReader(handle)
                        if 'Tracking Number' not in (reader.fieldnames or []):
                            raise RuntimeError('That file does not look like the FedEx shipping history export.')
                    command_output = StringIO()
                    call_command('import_shipping_history_csv', temp_path, stdout=command_output)
                    summary_line = command_output.getvalue().strip().splitlines()[-1]
                    messages.success(request, f"Imported shipping history from {upload.name}. {summary_line} Existing packages were only updated when the file contained newer information.")
                except Exception as exc:
                    messages.error(request, f'CSV import failed: {exc}')
                finally:
                    Path(temp_path).unlink(missing_ok=True)

        elif action == 'save_reference':
            label = (request.POST.get('reference_label') or '').strip()
            reference_value = (request.POST.get('reference_value') or '').strip()
            reference_type = (request.POST.get('reference_type') or 'CUSTOMER_REFERENCE').strip() or 'CUSTOMER_REFERENCE'
            notes = (request.POST.get('reference_notes') or '').strip()

            if not reference_value:
                messages.error(request, 'Reference value is required.')
            else:
                saved_reference, created = SavedReference.objects.get_or_create(
                    reference_value=reference_value,
                    defaults={
                        'label': label,
                        'reference_type': reference_type,
                        'notes': notes,
                    },
                )
                if not created:
                    changed = False
                    if label and saved_reference.label != label:
                        saved_reference.label = label
                        changed = True
                    if reference_type and saved_reference.reference_type != reference_type:
                        saved_reference.reference_type = reference_type
                        changed = True
                    if notes and saved_reference.notes != notes:
                        saved_reference.notes = notes
                        changed = True
                    if changed:
                        saved_reference.save()
                messages.success(request, f"Saved reference '{saved_reference.reference_value}'.")

        else:
            lookup_text = (request.POST.get('lookup') or '').strip()
            selected_reference_id = (request.POST.get('saved_reference_id') or '').strip()
            typed_reference_values = set(
                SavedReference.objects.filter(is_active=True).values_list('reference_value', flat=True)
            )
            ship_date_begin = (request.POST.get('ship_date_begin') or '').strip() or None
            ship_date_end = (request.POST.get('ship_date_end') or '').strip() or None
            destination_country_code = (request.POST.get('destination_country_code') or '').strip() or None
            destination_postal_code = (request.POST.get('destination_postal_code') or '').strip() or None
            account_number = (request.POST.get('account_number') or '').strip() or None
            reference_type = (request.POST.get('reference_type') or 'CUSTOMER_REFERENCE').strip() or 'CUSTOMER_REFERENCE'
            carrier_code = (request.POST.get('carrier_code') or '').strip() or 'FDXE'

            force_reference_lookup = False

            if selected_reference_id and not lookup_text:
                try:
                    saved_reference = SavedReference.objects.get(id=selected_reference_id, is_active=True)
                    lookup_text = saved_reference.reference_value
                    lookup_reference_label = saved_reference.label or saved_reference.reference_value
                    reference_type = saved_reference.reference_type or reference_type
                    force_reference_lookup = True
                    saved_reference.last_used_at = timezone.now()
                    saved_reference.save(update_fields=['last_used_at'])
                except SavedReference.DoesNotExist:
                    messages.error(request, 'Saved reference not found.')

            if lookup_text and lookup_text in typed_reference_values:
                force_reference_lookup = True
                if not lookup_reference_label:
                    saved_reference = SavedReference.objects.filter(reference_value=lookup_text, is_active=True).first()
                    if saved_reference:
                        lookup_reference_label = saved_reference.label or saved_reference.reference_value
                        reference_type = saved_reference.reference_type or reference_type

            if lookup_text:
                normalized_begin, normalized_end, date_error = validate_lookup_dates(ship_date_begin, ship_date_end)
                if date_error:
                    messages.error(request, date_error)
                else:
                    ship_date_begin = normalized_begin
                    ship_date_end = normalized_end
                    try:
                        result = lookup_and_store_packages(
                            lookup_text,
                            ship_date_begin=ship_date_begin,
                            ship_date_end=ship_date_end,
                            destination_country_code=destination_country_code,
                            destination_postal_code=destination_postal_code,
                            carrier_code=carrier_code,
                            account_number=account_number,
                            reference_type=reference_type,
                            force_reference_lookup=force_reference_lookup,
                        )
                        lookup_mode = result['mode']
                        lookup_results = result.get('candidates', [])
                        real_hits = [item for item in lookup_results if item.get('tracking_number') and not item.get('has_error')]
                        unresolved_rows = [item for item in lookup_results if item.get('has_error') or not item.get('tracking_number')]
                        api_not_found_count = sum(1 for item in unresolved_rows if item.get('status_code') == 'TRACKING.REFERENCENUMBER.NOTFOUND')
                        lookup_summary = {
                            'result_row_count': len(lookup_results),
                            'real_hit_count': len(real_hits),
                            'stored_count': len(result.get('packages', [])),
                            'unresolved_count': len(unresolved_rows),
                            'api_not_found_count': api_not_found_count,
                            'show_api_parity_note': bool(unresolved_rows and not real_hits and api_not_found_count),
                        }
                        if real_hits:
                            messages.success(
                                request,
                                f"FedEx returned {len(real_hits)} trackable package(s) for '{lookup_text}'. Saved {len(result.get('packages', []))} package(s) locally.",
                            )
                        else:
                            messages.warning(
                                request,
                                f"FedEx returned no trackable packages for '{lookup_text}' from the public API for this lookup.",
                            )
                    except Exception as exc:
                        messages.error(request, str(exc))

    packages = Package.objects.prefetch_related('events').all()[:500]
    if status_view == 'active':
        packages = [package for package in packages if (package.status or '').lower() not in {'delivered', 'cancelled'}]
    elif status_view == 'delivered':
        packages = [package for package in packages if (package.status or '').lower() == 'delivered']
    else:
        packages = list(packages)
    package_cards = build_package_cards(packages, query=query)

    if query:
        package_cards = [card for card in package_cards if card['matches_query']]

    if from_date or to_date:
        package_cards = [
            card for card in package_cards
            if package_in_date_range(card['package'], from_date, to_date)
        ]

    saved_references = SavedReference.objects.filter(is_active=True).order_by('label', 'reference_value')[:200]

    tracking_hits = [result for result in lookup_results if result.get('tracking_number') and not result.get('has_error')]
    persisted_hits = [result for result in lookup_results if result.get('persisted') and result.get('package')]
    unresolved_lookup_results = [result for result in lookup_results if result.get('has_error') or not result.get('tracking_number')]

    today = date.today()
    default_ship_date_end = today.isoformat()
    default_ship_date_begin = (today - timedelta(days=7)).isoformat()
    default_account_number = env('FEDEX_ACCOUNT_NUMBER', required=False, default='') or ''

    return render(request, 'tracker/home.html', {
        'package_cards': package_cards,
        'query': query,
        'from_date': from_date_raw,
        'to_date': to_date_raw,
        'status_view': status_view,
        'lookup_results': lookup_results,
        'lookup_mode': lookup_mode,
        'lookup_text': lookup_text,
        'lookup_reference_label': lookup_reference_label,
        'lookup_summary': lookup_summary,
        'saved_references': saved_references,
        'tracking_hits': tracking_hits,
        'persisted_hits': persisted_hits,
        'unresolved_lookup_results': unresolved_lookup_results,
        'default_ship_date_begin': default_ship_date_begin,
        'default_ship_date_end': default_ship_date_end,
        'default_account_number': default_account_number,
    })
