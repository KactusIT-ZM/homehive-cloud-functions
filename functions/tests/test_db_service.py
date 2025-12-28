import unittest
from unittest.mock import patch, MagicMock, call
import sys
import os

# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from functions.services.db_service import move_pending_to_due
from functions.constants import STATISTICS_PATH, ACCOUNTS_PATH

class TestDbService(unittest.TestCase):

    @patch('functions.services.db_service.db.reference')
    def test_move_pending_to_due(self, mock_db_reference):
        company_id = "test_company_id"
        payment_id = "test_payment_id"
        tenant_id = "test_tenant_id"
        payment_details = {
            'accountId': 'mjm2dme0g7lj9ukzmw8', 
            'amount': 8000, 
            'dueDate': '31/12/2025', 
            'lastUpdated': '2025-12-25T23:19:26.783Z', 
            'parentPropertyId': 'mcdy0kf4sfvxvub1rke', 
            'paymentId': '1766704766379fg6fze94e', 
            'paymentStatus': 1, 
            'paymentType': 0, 
            'propertyId': '1758235072928lyvinkkspd', 
            'propertyName': 'Big 4 - Unit 1', 
            'tenantId': 'mjm2dme0g7lj9ukzmw8', 
            'tenantName': 'Khondwani Sikasote', 
            'tenantType': 0
        }

        # Mock the Firebase reference objects and their methods
        mock_pending_ref = MagicMock()
        mock_due_ref = MagicMock()
        mock_account_payment_status_ref = MagicMock()
        mock_summary_ref = MagicMock()

        # Configure db.reference to return specific mocks based on the path
        # This is a common pattern when mocking hierarchical APIs
        def mock_reference_side_effect(path):
            if path == f"{STATISTICS_PATH}/{company_id}/paymentTracking/pending/{payment_id}":
                return mock_pending_ref
            elif path == f"{STATISTICS_PATH}/{company_id}/paymentTracking/due/{payment_id}":
                return mock_due_ref
            elif path == f"{ACCOUNTS_PATH}/{company_id}/{tenant_id}/payments/{payment_id}/paymentStatus":
                return mock_account_payment_status_ref
            elif path == f"{STATISTICS_PATH}/{company_id}/paymentTracking/summary":
                return mock_summary_ref
            return MagicMock() # Return a default mock for any other paths

        mock_db_reference.side_effect = mock_reference_side_effect

        # Mock the .get() call on the summary reference
        mock_summary_ref.get.return_value = {
            'pendingCount': 1,
            'pendingTotal': 8000.0,
            'dueCount': 0,
            'dueTotal': 0,
            'overdueCount': 0,
            'overdueTotal': 0,
            "partiallyPaidCount": 0,
            "partiallyPaidTotal": 0,
        }

        # Call the function under test
        move_pending_to_due(company_id, payment_id, payment_details, tenant_id)

        # Assertions
        
        # 1. Assert db.reference calls
        expected_db_reference_calls = [
            call(f"{STATISTICS_PATH}/{company_id}/paymentTracking/pending/{payment_id}"),
            call(f"{STATISTICS_PATH}/{company_id}/paymentTracking/due/{payment_id}"),
            call(f"{ACCOUNTS_PATH}/{company_id}/{tenant_id}/payments/{payment_id}/paymentStatus"),
            call(f"{STATISTICS_PATH}/{company_id}/paymentTracking/summary")
        ]
        # Using assert_has_calls with any_order=True as the order of calls to db.reference might vary depending on Python version/mock implementation details
        mock_db_reference.assert_has_calls(expected_db_reference_calls, any_order=True)

        # 2. Assert .set() calls
        mock_due_ref.set.assert_called_once_with(payment_details)
        mock_account_payment_status_ref.set.assert_called_once_with(2)

        # 3. Assert .delete() call
        mock_pending_ref.delete.assert_called_once()

        # 4. Assert summary update call
        expected_summary_update = {
            'pendingCount': 0,
            'pendingTotal': 0,
            'dueCount': 1,
            'dueTotal': 8000,
            'overdueCount': 0,
            'overdueTotal': 0,
            "partiallyPaidCount": 0,
            "partiallyPaidTotal": 0,
        }
        mock_summary_ref.update.assert_called_once_with(expected_summary_update)

    @patch('functions.services.db_service.db.reference')
    def test_move_due_to_overdue(self, mock_db_reference):
        company_id = "test_company_id"
        payment_id = "test_payment_id_due"
        tenant_id = "test_tenant_id"
        payment_details = {
            'accountId': 'test_tenant_id',
            'amount': 500.0,
            'dueDate': '23/12/2025',
            'lastUpdated': '2025-12-25T23:19:26.783Z',
            'parentPropertyId': 'mcdy0kf4sfvxvub1rke',
            'paymentId': 'test_payment_id_due',
            'paymentStatus': 2, # Currently due
            'paymentType': 0,
            'propertyId': '1758235072928lyvinkkspd',
            'propertyName': 'Big 4 - Unit 2',
            'tenantId': 'test_tenant_id',
            'tenantName': 'Khondwani Sikasote',
            'tenantType': 0
        }

        mock_due_ref = MagicMock()
        mock_overdue_ref = MagicMock()
        mock_account_payment_status_ref = MagicMock()
        mock_summary_ref = MagicMock()

        def mock_reference_side_effect(path):
            if path == f"{STATISTICS_PATH}/{company_id}/paymentTracking/due/{payment_id}":
                return mock_due_ref
            elif path == f"{STATISTICS_PATH}/{company_id}/paymentTracking/overdue/{payment_id}":
                return mock_overdue_ref
            elif path == f"{ACCOUNTS_PATH}/{company_id}/{tenant_id}/payments/{payment_id}/paymentStatus":
                return mock_account_payment_status_ref
            elif path == f"{STATISTICS_PATH}/{company_id}/paymentTracking/summary":
                return mock_summary_ref
            return MagicMock()

        mock_db_reference.side_effect = mock_reference_side_effect

        mock_summary_ref.get.return_value = {
            'pendingCount': 0,
            'pendingTotal': 0,
            'dueCount': 1,
            'dueTotal': 500.0,
            'overdueCount': 0,
            'overdueTotal': 0,
            "partiallyPaidCount": 0,
            "partiallyPaidTotal": 0,
        }

        from functions.services.db_service import move_payment_to_overdue
        move_payment_to_overdue(company_id, payment_id, payment_details, source_tracking_node='due')

        expected_db_reference_calls = [
            call(f"{STATISTICS_PATH}/{company_id}/paymentTracking/due/{payment_id}"),
            call(f"{STATISTICS_PATH}/{company_id}/paymentTracking/overdue/{payment_id}"),
            call(f"{ACCOUNTS_PATH}/{company_id}/{tenant_id}/payments/{payment_id}/paymentStatus"),
            call(f"{STATISTICS_PATH}/{company_id}/paymentTracking/summary")
        ]
        mock_db_reference.assert_has_calls(expected_db_reference_calls, any_order=True)

        mock_overdue_ref.set.assert_called_once_with(payment_details)
        mock_account_payment_status_ref.set.assert_called_once_with(3) # 3 for overdue

        mock_due_ref.delete.assert_called_once()

        expected_summary_update = {
            'pendingCount': 0,
            'pendingTotal': 0,
            'dueCount': 0,
            'dueTotal': 0,
            'overdueCount': 1,
            'overdueTotal': 500.0,
            "partiallyPaidCount": 0,
            "partiallyPaidTotal": 0,
        }
        mock_summary_ref.update.assert_called_once_with(expected_summary_update)

if __name__ == '__main__':
    unittest.main()
