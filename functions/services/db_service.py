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

def move_pending_to_due(company_id: str, payment_id: str, payment_details: dict, tenant_id: str):
    """
    Moves a payment from pending to due in Firebase Realtime Database and updates counts and totals.
    """
    try:
        pending_ref = db.reference(f"{STATISTICS_PATH}/{company_id}/paymentTracking/pending/{payment_id}")
        due_ref = db.reference(f"{STATISTICS_PATH}/{company_id}/paymentTracking/due/{payment_id}") # Node name is 'due'
        
        if tenant_id: # tenant_id is now passed as an argument
            account_payment_status_ref = db.reference(f"/HomeHive/PropertyManagement/Accounts/{company_id}/{tenant_id}/payments/{payment_id}/paymentStatus")
            account_payment_status_ref.set(2) # 2 for due
        else:
            log.warning(f"tenant_id not provided for payment {payment_id} in company {company_id}. Account payment status not updated.")

        # Get the amount of the payment being moved
        amount = float(payment_details.get('amount', 0))


        due_ref.set(payment_details)
        
        pending_ref.delete()

        # Update summary counts and totals
        summary_ref = db.reference(f"{STATISTICS_PATH}/{company_id}/paymentTracking/summary")
        summary_data = summary_ref.get()
        if summary_data:
            summary_data['pendingCount'] = summary_data.get('pendingCount', 0) - 1
            summary_data['pendingTotal'] = summary_data.get('pendingTotal', 0) - amount # Decrement pendingTotal
            
            summary_data['dueCount'] = summary_data.get('dueCount', 0) + 1 
            summary_data['dueTotal'] = summary_data.get('dueTotal', 0) + amount # Increment dueTotal
            summary_ref.update(summary_data)
        
        log.info(f"Successfully moved payment {payment_id} to due for company {company_id}")
    except Exception as e:
        log.error(f"Error moving payment {payment_id} to due for company {company_id}: {e}")

def move_payment_to_overdue(company_id: str, payment_id: str, payment_details: dict, source_tracking_node: str = "pending"):
    """
    Moves a payment from a specified source tracking node to overdue in Firebase Realtime Database
    and updates counts and totals.
    """
    try:
        source_ref = db.reference(f"{STATISTICS_PATH}/{company_id}/paymentTracking/{source_tracking_node}/{payment_id}")
        overdue_ref = db.reference(f"{STATISTICS_PATH}/{company_id}/paymentTracking/overdue/{payment_id}")
        
        overdue_ref.set(payment_details)
        
        source_ref.delete()
        tenant_id = payment_details.get('tenantId', '')
        if tenant_id:
            account_payment_status_ref = db.reference(f"/HomeHive/PropertyManagement/Accounts/{company_id}/{tenant_id}/payments/{payment_id}/paymentStatus")
            account_payment_status_ref.set(3) # 3 for overdue
        else:
            log.warning(f"tenant_id not provided for payment {payment_id} in company {company_id}. Account payment status not updated.")

        # Get the amount of the payment being moved
        amount = float(payment_details.get('amount', 0))

        # Update summary counts and totals
        summary_ref = db.reference(f"{STATISTICS_PATH}/{company_id}/paymentTracking/summary")
        summary_data = summary_ref.get()
        if summary_data:
            # Decrement source status counts
            summary_data[f'{source_tracking_node}Count'] = summary_data.get(f'{source_tracking_node}Count', 0) - 1
            summary_data[f'{source_tracking_node}Total'] = summary_data.get(f'{source_tracking_node}Total', 0) - amount
            
            # Increment overdue counts
            summary_data['overdueCount'] = summary_data.get('overdueCount', 0) + 1
            summary_data['overdueTotal'] = summary_data.get('overdueTotal', 0) + amount
            summary_ref.update(summary_data)
        
        log.info(f"Successfully moved payment {payment_id} from {source_tracking_node} to overdue for company {company_id}")
    except Exception as e:
        log.error(f"Error moving payment {payment_id} from {source_tracking_node} to overdue for company {company_id}: {e}")
