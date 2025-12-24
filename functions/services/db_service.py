# functions/db_service.py

import firebase_admin.db as db
import logging

from constants import TENANTS_PATH, STATISTICS_PATH

log = logging.getLogger(__name__)

def get_all_tenants() -> dict:
    """
    Gets all tenants from the Firebase Realtime Database.
    """
    ref = db.reference(TENANTS_PATH)
    tenants = ref.get()
    return tenants if tenants else {}

def get_all_accounts() -> dict:
    """
    Gets all accounts from the Firebase Realtime Database.
    """
    ref = db.reference('/HomeHive/PropertyManagement/Accounts')
    accounts = ref.get()
    return accounts if accounts else {}

def get_all_statistics() -> dict:
    """
    Gets all statistics from the Firebase Realtime Database.
    """
    ref = db.reference(STATISTICS_PATH)
    stats = ref.get()
    return stats if stats else {}

def get_all_companies() -> dict:
    """
    Gets all companies from the Firebase Realtime Database.
    """
    ref = db.reference('/HomeHive/PropertyManagement/Companies')
    companies = ref.get()
    return companies if companies else {}

def move_payment_to_overdue(company_id: str, payment_id: str, payment_details: dict):
    """
    Moves a payment from pending to overdue in Firebase Realtime Database and updates counts.
    """
    try:
        pending_ref = db.reference(f"{STATISTICS_PATH}/{company_id}/paymentTracking/pending/{payment_id}")
        overdue_ref = db.reference(f"{STATISTICS_PATH}/{company_id}/paymentTracking/overdue/{payment_id}")
        
        overdue_ref.set(payment_details)
        
        pending_ref.delete()

        # Update summary counts
        summary_ref = db.reference(f"{STATISTICS_PATH}/{company_id}/paymentTracking/summary")
        summary_data = summary_ref.get()
        if summary_data:
            summary_data['pendingCount'] = summary_data.get('pendingCount', 0) - 1
            summary_data['overdueCount'] = summary_data.get('overdueCount', 0) + 1
            summary_ref.update(summary_data)
        
        log.info(f"Successfully moved payment {payment_id} to overdue for company {company_id}")
    except Exception as e:
        log.error(f"Error moving payment {payment_id} to overdue for company {company_id}: {e}")
