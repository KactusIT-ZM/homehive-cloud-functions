import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from flask import Flask
from datetime import date, timedelta
import copy
import logging
import firebase_admin # Added for mocking

# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Now we can import from main
from functions.main import (
    main as notification_handler,
    send_notification_worker
)
from functions.services.db_service import get_all_tenants, get_all_accounts
from functions.logic.notification_logic import get_due_tenants_for_reminders, _flatten_tenants
from functions.services.cloud_tasks_service import enqueue_notification_tasks
from functions.services.email_service import send_reminder_email
from firebase_functions import https_fn

class MockEvent:
    """A mock event object for testing Cloud Functions."""
    def __init__(self):
        self.headers = {}

class TestHelperFunctions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        json_file_path = os.path.join(current_dir, 'test_db.json')
        with open(json_file_path, 'r') as f:
            cls.full_db_data = json.load(f)
        cls.tenants_data = cls.full_db_data["HomeHive"]["PropertyManagement"]["Tenants"]
        cls.accounts_data = cls.full_db_data["HomeHive"]["PropertyManagement"]["Accounts"] # Keep for existing tests if needed
        cls.statistics_data = cls.full_db_data["HomeHive"]["PropertyManagement"]["Statistics"]

    def test_flatten_tenants(self):
        flat_tenants = _flatten_tenants(self.tenants_data)
        self.assertIn('mcevbmtsrr1b3k608cm', flat_tenants)
        self.assertEqual(flat_tenants['mcevbmtsrr1b3k608cm']['email'], 'saadaq301@gmail.com')

    def test_get_due_tenants_for_reminders_with_statistics_data(self):
        mock_today = date(2025, 12, 24) # Today is 24/12/2025
        
        # Mock data for tenants
        mock_tenants_data = {
            "company_id_1": {
                "active": {
                    "tenant_id_rental": {
                        "email": "rental@example.com",
                        "mobileNumber": "1112223333"
                    },
                    "tenant_id_non_rental": {
                        "email": "nonrental@example.com",
                        "mobileNumber": "4445556666"
                    }
                }
            }
        }

        # Mock data for statistics
        mock_statistics_data = {
            "company_id_1": {
                "paymentTracking": {
                    "pending": {
                        "payment_id_rental": {
                            "amount": 1000,
                            "dueDate": "28/12/2025", # Within 7-day window from 2025-12-24
                            "paymentType": 0, # Rental payment - should be included
                            "tenantId": "tenant_id_rental",
                            "tenantName": "Rental Tenant",
                            "propertyName": "Rental Property"
                        },
                        "payment_id_non_rental": {
                            "amount": 500,
                            "dueDate": "27/12/2025", # Within 7-day window from 2025-12-24
                            "paymentType": 1, # Non-rental payment - should be excluded
                            "tenantId": "tenant_id_non_rental",
                            "tenantName": "Non-Rental Tenant",
                            "propertyName": "Non-Rental Property"
                        }
                    }
                }
            }
        }

        with patch('functions.logic.notification_logic.date') as mock_date:
            mock_date.today.return_value = mock_today
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw) # Allow normal date constructor

            due_tenants = get_due_tenants_for_reminders(mock_statistics_data, mock_tenants_data, 7)
            
            self.assertIsInstance(due_tenants, list)

            # Assert that the rental payment is included
            rental_tenant_found = False
            for tenant_info in due_tenants:
                if tenant_info.get('tenant_id') == 'tenant_id_rental':
                    rental_tenant_found = True
                    self.assertEqual(tenant_info['name'], 'Rental Tenant')
                    self.assertEqual(tenant_info['email'], 'rental@example.com')
                    self.assertEqual(tenant_info['dueDate'], '28/12/2025')
                    self.assertEqual(tenant_info['rent_amount'], 1000)
                    self.assertEqual(tenant_info['property_name'], 'Rental Property')
                    break
            self.assertTrue(rental_tenant_found, "Rental payment was not found in due tenants.")

            # Assert that the non-rental payment is NOT included
            non_rental_tenant_found = any(t.get('tenant_id') == 'tenant_id_non_rental' for t in due_tenants)
            self.assertFalse(non_rental_tenant_found, "Non-rental payment should have been excluded but was found.")


class TestMainIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        json_file_path = os.path.join(current_dir, 'test_db.json')
        with open(json_file_path, 'r') as f:
            cls.full_db_data = json.load(f)
        cls.app = Flask(__name__)

    def setUp(self):
        # Mock Firebase app initialization
        self.patch_initialize_app = patch('firebase_admin.initialize_app')
        self.mock_initialize_app = self.patch_initialize_app.start()

        # Mock Firebase db reference
        self.patch_db_reference = patch('firebase_admin.db.reference')
        self.mock_db_reference = self.patch_db_reference.start()
        # Configure mock for .get() calls
        mock_ref_instance = MagicMock()
        mock_ref_instance.get.side_effect = self._mock_db_get

        # Ensure that db.reference returns a mock object that has a .get method
        self.mock_db_reference.return_value = mock_ref_instance

        self.patch_enqueue = patch('functions.main.enqueue_notification_tasks')
        self.patch_get_tenants = patch('functions.main.get_all_tenants')
        self.patch_get_statistics = patch('functions.main.get_all_statistics')
        
        self.mock_enqueue = self.patch_enqueue.start()
        self.mock_get_tenants = self.patch_get_tenants.start()
        self.mock_get_statistics = self.patch_get_statistics.start()

    def tearDown(self):
        patch.stopall()

    def _mock_db_get(self, path=None):
        """Mocks the Firebase db.reference().get() method."""
        if path == '/HomeHive/PropertyManagement/Accounts': # Old path, might still be used by some logic
            return self.full_db_data["HomeHive"]["PropertyManagement"]["Accounts"]
        elif path == '/HomeHive/PropertyManagement/Tenants':
            return self.full_db_data["HomeHive"]["PropertyManagement"]["Tenants"]
        elif path == '/HomeHive/PropertyManagement/Statistics':
            return self.full_db_data["HomeHive"]["PropertyManagement"]["Statistics"]
        return None

    def test_notification_handler_flow_enqueues_task_for_due_tenant(self):
        statistics_data = copy.deepcopy(self.full_db_data["HomeHive"]["PropertyManagement"]["Statistics"])
        tenants_data = copy.deepcopy(self.full_db_data["HomeHive"]["PropertyManagement"]["Tenants"])
        
        # We need to mock these to control the return values precisely
        self.mock_get_statistics.return_value = statistics_data
        self.mock_get_tenants.return_value = tenants_data
        
        mock_event = MockEvent()

        with self.app.app_context():
            with patch('functions.logic.notification_logic.date') as mock_date_logic, \
                 patch('functions.main.get_due_tenants_for_reminders') as mock_get_due_tenants:
                mock_date_logic.today.return_value = date(2025, 12, 24) # Set a fixed date for the test
                mock_date_logic.side_effect = lambda *args, **kw: date(*args, **kw) # Allow normal date constructor

                # Mock to ensure enqueue is called with the expected tenant_info
                mock_get_due_tenants.return_value = [{
                    'tenant_id': 'milsdwu5nuas68mef6', 
                    'name': 'Koozya Sikasote', 
                    'email': 'koozya@gmail.com', 
                    'mobileNumber': '0743794740',
                    'dueDate': '28/12/2025',
                    'rent_amount': 3000,
                    'property_name': 'CJ Flats - Unit 4'
                }] 
                notification_handler(mock_event)
        
        mock_get_due_tenants.assert_called_once_with(statistics_data, tenants_data, 7) # Assert args
        self.assertTrue(self.mock_enqueue.called)

class TestNotificationWorker(unittest.TestCase):
    @patch.dict(os.environ, {
        "SENDER_EMAIL": "test@example.com", 
        "TESTING_MODE": "false" # Explicitly disable testing mode
    })
    @patch('functions.services.email_service.boto3.client')
    @patch('functions.services.email_service.access_secret_version')
    def test_send_email_success(self, mock_access_secret_version, mock_boto_client):
        mock_access_secret_version.side_effect = ["mock_aws_access_key", "mock_aws_secret_key"]
        mock_ses_instance = mock_boto_client.return_value
        mock_ses_instance.send_raw_email.return_value = {} # send_raw_email is now always used
        
        tenant_info = {
            'tenant_id': 'test-tenant-1', 
            'name': 'Test Tenant', 
            'email': 'recipient@example.com', 
            'dueDate': '25/12/2025',
            'rent_amount': 1000,
            'property_name': 'Test Property'
        }
        mock_request = MagicMock(spec=https_fn.Request)
        mock_request.get_json.return_value = tenant_info

        with patch('functions.services.invoice_service.create_invoice_pdf') as mock_create_invoice_pdf, \
             patch('functions.main.template_env') as mock_template_env: # Patch template_env
            mock_create_invoice_pdf.return_value = b'mock_pdf_data'
            mock_template_env.get_template.return_value.render.return_value = 'mock_html_body'

            response = send_notification_worker(mock_request)

            self.assertEqual(response.status_code, 200)
            mock_ses_instance.send_raw_email.assert_called_once()
            call_args = mock_ses_instance.send_raw_email.call_args[1]
            # Further assertions on RawMessage content can be added if needed
            self.assertEqual(call_args['Destinations'], ['recipient@example.com'])

    @patch.dict(os.environ, {
        "SENDER_EMAIL": "test@example.com", 
        "TESTING_MODE": "true"
    })
    @patch('functions.services.email_service.log')
    @patch('functions.services.email_service.boto3.client')
    @patch('functions.services.email_service.access_secret_version')
    def test_send_email_testing_mode_redirects_email(self, mock_access_secret_version, mock_boto_client, mock_log):
        mock_access_secret_version.side_effect = ["mock_aws_access_key", "mock_aws_secret_key"]
        mock_ses_instance = mock_boto_client.return_value
        mock_ses_instance.send_raw_email.return_value = {} # send_raw_email is now always used
        
        tenant_info = {
            'tenant_id': 'test-tenant-1', 
            'name': 'Test Tenant', 
            'email': 'original.recipient@example.com', 
            'dueDate': '25/12/2025',
            'rent_amount': 1000,
            'property_name': 'Test Property'
        }
        mock_request = MagicMock(spec=https_fn.Request)
        mock_request.get_json.return_value = tenant_info

        with patch('functions.services.invoice_service.create_invoice_pdf') as mock_create_invoice_pdf, \
             patch('functions.main.template_env') as mock_template_env: # Patch template_env
            mock_create_invoice_pdf.return_value = b'mock_pdf_data'
            mock_template_env.get_template.return_value.render.return_value = 'mock_html_body'

            response = send_notification_worker(mock_request)

            self.assertEqual(response.status_code, 200)
            mock_ses_instance.send_raw_email.assert_called_once()
            call_args = mock_ses_instance.send_raw_email.call_args[1]
            self.assertEqual(call_args['Destinations'], ['info@kactusit.com'])

if __name__ == '__main__':
    unittest.main()
