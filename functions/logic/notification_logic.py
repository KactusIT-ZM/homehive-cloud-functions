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

def get_due_tenants_for_reminders(statistics: dict, tenants: dict, days_window: int) -> list:
    """
    Identifies tenants with rent due within the configured window by processing pending payments from statistics.
    """
    today = date.today()
    due_date_upper_bound = today + timedelta(days=days_window)
    all_tenants_flat = _flatten_tenants(tenants)
    
    all_due_tenants = []

    for company_id, company_stats in statistics.items():
        pending_payments = company_stats.get('paymentTracking', {}).get('pending', {})
        for payment_id, payment_details in pending_payments.items():
            # If paymentType is 0, it's a rental payment. Only consider rental payments for reminders.
            if payment_details.get('paymentType') != 0:
                continue

            rent_due_date_str = payment_details.get('dueDate').strip()
            if not rent_due_date_str:
                continue

            try:
                due_date = datetime.strptime(rent_due_date_str, '%d/%m/%Y').date()
                if today <= due_date <= due_date_upper_bound:
                    tenant_id = payment_details.get('tenantId')
                    tenant_details_from_db = all_tenants_flat.get(tenant_id)
                    if tenant_details_from_db:
                        tenant_info = {
                            'tenant_id': tenant_id,
                            'name': payment_details.get('tenantName', ''),
                            'email': tenant_details_from_db.get('email'),
                            'mobileNumber': tenant_details_from_db.get('mobileNumber'),
                            'dueDate': due_date.strftime('%d/%m/%Y'),
                            'rent_amount': payment_details.get('amount'),
                            'property_name': payment_details.get('propertyName', ''),
                            'payment_id': payment_id
                        }
                        all_due_tenants.append(tenant_info)
            except (ValueError, TypeError):
                log.warning(f"Could not parse date '{rent_due_date_str}' for payment {payment_id}")
                continue
                
    return all_due_tenants

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
