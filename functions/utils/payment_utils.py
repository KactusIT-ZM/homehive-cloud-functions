import logging

log = logging.getLogger(__name__)

def find_tenant_id_for_payment(company_id: str, payment_id: str, all_accounts: dict) -> str | None:
    """
    Finds the tenant_id for a given payment_id within a company's accounts.
    """
    company_accounts = all_accounts.get(company_id)
    if not company_accounts:
        log.warning(f"No accounts found for company_id: {company_id} when trying to find tenant_id for payment {payment_id}")
        return None

    for tenant_id, tenant_data in company_accounts.items():
        if tenant_data and 'payments' in tenant_data and payment_id in tenant_data['payments']:
            return tenant_id
    
    log.warning(f"Could not find tenant_id for payment {payment_id} in company {company_id}'s accounts.")
    return None
