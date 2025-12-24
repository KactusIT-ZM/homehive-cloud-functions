# functions/db_service.py

import firebase_admin.db as db
from constants import TENANTS_PATH, STATISTICS_PATH

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
