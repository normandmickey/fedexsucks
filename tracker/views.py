import csv
from io import StringIO
from datetime import date, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.conf import settings as project_settings
from django.contrib.auth import login as auth_login
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET
from django.utils import timezone

from .fedex import env, fetch_tracking_result, first_result, load_local_env
from .internal_api import InternalAPIAuthError, get_package_or_404, require_internal_api_key, search_packages, serialize_package_detail
from .models import CarrierCredential, Package, SavedReference
from .credentials import decrypt_secret, encrypt_secret, mask
from .services import lookup_and_store_packages, upsert_package_from_result

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
        package = Package.objects.prefetch_related('events').get(tracking_number=tracking_number, owner=request.user)
    except Package.DoesNotExist as exc:
        raise Http404('Package not found') from exc

    if request.method == 'POST' and (request.POST.get('action') or '').strip() == 'refresh_tracking':
        try:
            payload, result = fetch_tracking_result(tracking_number)
            imported_csv_row = (package.last_raw_payload or {}).get('imported_csv_row')
            if imported_csv_row:
                payload['imported_csv_row'] = imported_csv_row
            package = upsert_package_from_result(result, payload, nickname=package.nickname, owner=request.user)
            messages.success(request, f'Refreshed {tracking_number} from FedEx.')
        except Exception as exc:
            messages.error(request, f'FedEx refresh failed for {tracking_number}: {exc}')
        package = Package.objects.prefetch_related('events').get(tracking_number=tracking_number, owner=request.user)

    card = build_package_ui_snapshot(package)
    return render(request, 'tracker/package_detail.html', {
        'card': card,
        'package': package,
    })


@require_GET
def internal_api_health(request: HttpRequest) -> HttpResponse:
    try:
        require_internal_api_key(request)
    except InternalAPIAuthError as exc:
        return JsonResponse({'detail': str(exc)}, status=401)

    return JsonResponse({
        'ok': True,
        'service': 'fedexsucks',
        'api': 'internal',
    })


@require_GET
def internal_api_package_search(request: HttpRequest) -> HttpResponse:
    try:
        require_internal_api_key(request)
    except InternalAPIAuthError as exc:
        return JsonResponse({'detail': str(exc)}, status=401)

    query = (request.GET.get('q') or '').strip()
    try:
        limit = int((request.GET.get('limit') or '10').strip())
    except ValueError:
        limit = 10
    limit = max(1, min(limit, 25))

    return JsonResponse({
        'query': query,
        'results': search_packages(query, limit=limit),
    })


@require_GET
def internal_api_package_detail(request: HttpRequest, tracking_number: str) -> HttpResponse:
    try:
        require_internal_api_key(request)
    except InternalAPIAuthError as exc:
        return JsonResponse({'detail': str(exc)}, status=401)

    package = get_package_or_404(tracking_number)
    return JsonResponse(serialize_package_detail(package))


@require_GET
def internal_api_package_latest_status(request: HttpRequest, tracking_number: str) -> HttpResponse:
    try:
        require_internal_api_key(request)
    except InternalAPIAuthError as exc:
        return JsonResponse({'detail': str(exc)}, status=401)

    package = get_package_or_404(tracking_number)
    detail = serialize_package_detail(package)
    return JsonResponse({
        'package': detail['package'],
        'latest_event': detail['events'][0] if detail['events'] else None,
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
                    from tracker.csv_formats import looks_like_fedex_history, map_columns

                    with open(temp_path, newline='', encoding='utf-8-sig') as handle:
                        reader = csv.DictReader(handle)
                        fieldnames = reader.fieldnames or []
                    if 'tracking' not in map_columns(fieldnames):
                        raise RuntimeError('Could not find a tracking number column in that CSV.')
                    command_output = StringIO()
                    if looks_like_fedex_history(fieldnames):
                        call_command('import_shipping_history_csv', temp_path, '--user-id', str(request.user.id), stdout=command_output)
                    else:
                        call_command('import_packages_csv', temp_path, '--user-id', str(request.user.id), stdout=command_output)
                    summary_line = command_output.getvalue().strip().splitlines()[-1]
                    messages.success(request, f"Imported packages from {upload.name}. {summary_line} Existing packages were only updated when the file contained newer information.")
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
                    owner=request.user,
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
                SavedReference.objects.filter(is_active=True, owner=request.user).values_list('reference_value', flat=True)
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
                    saved_reference = SavedReference.objects.get(id=selected_reference_id, is_active=True, owner=request.user)
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
                    saved_reference = SavedReference.objects.filter(reference_value=lookup_text, is_active=True, owner=request.user).first()
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
                            owner=request.user,
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

    packages = Package.objects.prefetch_related('events').filter(owner=request.user)[:500]
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

    saved_references = SavedReference.objects.filter(is_active=True, owner=request.user).order_by('label', 'reference_value')[:200]

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


def register(request: HttpRequest) -> HttpResponse:
    invite_code = (getattr(project_settings, 'REGISTER_INVITE_CODE', '') or '').strip()
    if not invite_code:
        messages.info(request, 'Registration is currently closed.')
        return redirect('login')

    if request.method == 'POST':
        supplied_code = (request.POST.get('invite_code') or '').strip()
        form = UserCreationForm(request.POST)
        if supplied_code != invite_code:
            messages.error(request, 'That invite code is not valid.')
        elif form.is_valid():
            user = form.save()
            auth_login(request, user)
            messages.success(request, f'Welcome, {user.username}. Your workspace is ready.')
            return redirect('home')
    else:
        form = UserCreationForm()

    return render(request, 'registration/register.html', {'form': form})


CARRIER_KEY_SHAPES = {
    'fedex': {
        'label': 'FedEx',
        'api_label': 'API key',
        'secret_label': 'Secret key',
        'needs_secret': True,
        'account_field': True,
        'hint': 'developer.fedex.com — Production API key + secret.',
    },
    'ups': {
        'label': 'UPS',
        'api_label': 'Client ID',
        'secret_label': 'Client secret',
        'needs_secret': True,
        'account_field': False,
        'hint': 'developer.ups.com (Developer Kit) — OAuth client ID + secret.',
    },
    'usps': {
        'label': 'USPS',
        'api_label': 'API key',
        'secret_label': '',
        'needs_secret': False,
        'account_field': False,
        'hint': 'registration.usps.com — X-API-Key.',
    },
}


@login_required
def carrier_keys(request: HttpRequest) -> HttpResponse:
    """Tenant BYOK dashboard: add, review (masked), and delete carrier API keys."""
    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        carrier = (request.POST.get('carrier') or '').strip()
        if carrier not in CARRIER_KEY_SHAPES:
            messages.error(request, 'Unknown carrier.')
            return redirect('carrier_keys')
        shape = CARRIER_KEY_SHAPES[carrier]
        if action == 'delete':
            deleted, _ = CarrierCredential.objects.filter(
                owner=request.user, carrier=carrier).delete()
            if deleted:
                messages.success(request, f'{shape["label"]} keys removed.')
            return redirect('carrier_keys')
        if action == 'save':
            api_key = (request.POST.get('api_key') or '').strip()
            secret_key = (request.POST.get('secret_key') or '').strip()
            account_number = (request.POST.get('account_number') or '').strip()
            if not api_key or (shape['needs_secret'] and not secret_key):
                messages.error(request, f'Fill in every required {shape["label"]} field.')
            else:
                CarrierCredential.objects.update_or_create(
                    owner=request.user, carrier=carrier,
                    defaults={
                        'api_key_enc': encrypt_secret(api_key),
                        'secret_key_enc': encrypt_secret(secret_key),
                        'account_number': account_number,
                    })
                messages.success(request, f'{shape["label"]} keys saved — encrypted at rest.')
            return redirect('carrier_keys')

    creds = {c.carrier: c for c in
             CarrierCredential.objects.filter(owner=request.user)}
    cards = []
    for carrier, shape in CARRIER_KEY_SHAPES.items():
        cred = creds.get(carrier)
        cards.append({
            'carrier': carrier,
            'label': shape['label'],
            'hint': shape['hint'],
            'needs_secret': shape['needs_secret'],
            'account_field': shape['account_field'],
            'api_label': shape['api_label'],
            'secret_label': shape['secret_label'],
            'is_set': bool(cred),
            'masked_api': mask(decrypt_secret(cred.api_key_enc)) if cred else '',
            'masked_secret': mask(decrypt_secret(cred.secret_key_enc)) if cred else '',
            'account_number': cred.account_number if cred else '',
            'updated_at': cred.updated_at if cred else None,
        })
    return render(request, 'tracker/api_keys.html', {'cards': cards})
