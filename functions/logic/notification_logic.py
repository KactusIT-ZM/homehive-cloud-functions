from datetime import datetime, date, timedelta
import logging

# Set up a module-level logger
log = logging.getLogger(__name__)

def _flatten_tenants(tenants: dict) -> dict:
    """Creates a flattened dictionary of tenants for quick lookups."""
    return {
        tenant_id: tenant_data
        for company_tenants in tenants.values()
        for status_group in company_tenants.values()
        for tenant_id, tenant_data in status_group.items()
    }

def get_due_rentals_by_tenant(statistics: dict, tenants: dict, exact_days_from_today: int) -> dict:
    """
    Identifies rental payments due exactly `exact_days_from_today` from today, grouped by tenant ID.
    Returns a dictionary where keys are tenant IDs and values are dicts containing tenant_info and a list of their due rentals.
    """
    today = date.today()
    target_due_date = today + timedelta(days=exact_days_from_today)
    all_tenants_flat = _flatten_tenants(tenants)
    
    # Structure: {tenant_id: {'tenant_info': {...}, 'due_rentals': [...]}}
    grouped_due_rentals_by_tenant = {} 

    for company_id, company_stats in statistics.items():
        pending_payments = company_stats.get('paymentTracking', {}).get('pending', {})
        for payment_id, payment_details in pending_payments.items():
            # Only consider rental payments (paymentType == 0)
            if payment_details.get('paymentType') != 0:
                continue

            rent_due_date_str = payment_details.get('dueDate').strip()
            if not rent_due_date_str:
                continue

            try:
                due_date = datetime.strptime(rent_due_date_str, '%d/%m/%Y').date()
                if due_date == target_due_date: # Check for exact due date
                    tenant_id = payment_details.get('tenantId')
                    tenant_details_from_db = all_tenants_flat.get(tenant_id)
                    if tenant_details_from_db:
                        if tenant_id not in grouped_due_rentals_by_tenant:
                            grouped_due_rentals_by_tenant[tenant_id] = {
                                'tenant_info': {
                                    'tenant_id': tenant_id,
                                    'name': payment_details.get('tenantName', ''),
                                    'email': tenant_details_from_db.get('email'),
                                    'mobileNumber': tenant_details_from_db.get('mobileNumber'),
                                },
                                'due_rentals': []
                            }
                        
                        # Add individual rental details to the tenant's list
                        grouped_due_rentals_by_tenant[tenant_id]['due_rentals'].append({
                            'dueDate': due_date.strftime('%d/%m/%Y'),
                            'rent_amount': payment_details.get('amount'),
                            'property_name': payment_details.get('propertyName', ''),
                            'payment_id': payment_id,
                            'company_id': company_id # Add company_id here
                        })
            except (ValueError, TypeError):
                log.warning(f"Could not parse date '{rent_due_date_str}' for payment {payment_id}")
                continue
    return grouped_due_rentals_by_tenant

def get_due_rentals_by_landlord(statistics: dict, tenants: dict, companies: dict, exact_days_from_today: int) -> dict:
    """
    Identifies rental payments due exactly `exact_days_from_today` from today, grouped by landlord email.
    Each landlord receives a summary of all due rentals for their associated properties.
    """
    today = date.today()
    target_due_date = today + timedelta(days=exact_days_from_today)
    all_tenants_flat = _flatten_tenants(tenants)
    
    landlord_due_rentals = {} # Key: landlord_email, Value: list of rental details

    for company_id, company_stats in statistics.items():
        # Get landlord email for this company
        landlord_email = companies.get(company_id, {}).get('contactEmail')
        if not landlord_email:
            log.warning(f"No contact email found for company ID: {company_id}. Skipping landlord notification.")
            continue

        pending_payments = company_stats.get('paymentTracking', {}).get('pending', {})
        for payment_id, payment_details in pending_payments.items():
            # Only consider rental payments (paymentType == 0)
            if payment_details.get('paymentType') != 0:
                continue

            rent_due_date_str = payment_details.get('dueDate').strip()
            if not rent_due_date_str:
                continue

            try:
                due_date = datetime.strptime(rent_due_date_str, '%d/%m/%Y').date()
                if due_date == target_due_date: # Check for exact due date
                    tenant_id = payment_details.get('tenantId')
                    tenant_details_from_db = all_tenants_flat.get(tenant_id)
                    if tenant_details_from_db:
                        rental_info = {
                            'tenant_name': payment_details.get('tenantName', ''),
                            'property_name': payment_details.get('propertyName', ''),
                            'amount': payment_details.get('amount'),
                            'due_date': due_date.strftime('%d/%m/%Y'),
                        }
                        if landlord_email not in landlord_due_rentals:
                            landlord_due_rentals[landlord_email] = []
                        landlord_due_rentals[landlord_email].append(rental_info)
            except (ValueError, TypeError):
                log.warning(f"Could not parse date '{rent_due_date_str}' for payment {payment_id}")
                continue
                
    return landlord_due_rentals

def get_payments_to_move_to_overdue(statistics: dict) -> list:
    """
    Identifies payments that are past their due date and need to be moved to the overdue section.
    Returns a list of dictionaries, each containing company_id, payment_id, and payment_details.
    """
    today = date.today()
    payments_to_move = []

    for company_id, company_stats in statistics.items():
        pending_payments = company_stats.get('paymentTracking', {}).get('pending', {})
        for payment_id, payment_details in pending_payments.items():
            rent_due_date_str = payment_details.get('dueDate').strip()
            if not rent_due_date_str:
                continue

            try:
                due_date = datetime.strptime(rent_due_date_str, '%d/%m/%Y').date()
                if due_date < today:
                    payments_to_move.append({
                        'company_id': company_id,
                        'payment_id': payment_id,
                        'payment_details': payment_details
                    })
            except (ValueError, TypeError):
                log.warning(f"Could not parse date '{rent_due_date_str}' for payment {payment_id}")
                continue
    return payments_to_move

def get_payments_to_move_to_due_soon(statistics: dict, exact_days_from_today: int) -> list:
    """
    Identifies payments in the 'pending' state that are due exactly `exact_days_from_today` days from today.
    Returns a list of dictionaries, each containing company_id, payment_id, and payment_details.
    Includes all payment types (rental and non-rental).
    """
    today = date.today()
    target_due_date = today + timedelta(days=exact_days_from_today)
    payments_to_move = []

    for company_id, company_stats in statistics.items():
        pending_payments = company_stats.get('paymentTracking', {}).get('pending', {})
        for payment_id, payment_details in pending_payments.items():
            rent_due_date_str = payment_details.get('dueDate').strip()
            if not rent_due_date_str:
                continue

            try:
                due_date = datetime.strptime(rent_due_date_str, '%d/%m/%Y').date()
                if due_date == target_due_date: # Check for exact due date
                    payments_to_move.append({
                        'company_id': company_id,
                        'payment_id': payment_id,
                        'payment_details': payment_details
                    })
            except (ValueError, TypeError):
                log.warning(f"Could not parse date '{rent_due_date_str}' for payment {payment_id}")
                continue
    return payments_to_move

