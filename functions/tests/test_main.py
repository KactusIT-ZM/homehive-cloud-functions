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
from unittest.mock import patch, MagicMock, ANY

# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Now we can import from main
from functions.main import (
    main as notification_handler,
    send_notification_worker
)
from functions.services.db_service import get_all_tenants, get_all_accounts, move_payment_to_due
from functions.logic.notification_logic import get_due_rentals_by_tenant, _flatten_tenants, get_due_rentals_by_landlord, get_payments_to_move_to_due_soon
from functions.services.cloud_tasks_service import enqueue_notification_tasks
from functions.services.email_service import send_tenant_summary_email, send_landlord_summary_email
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

    def test_get_due_rentals_by_tenant(self):
        mock_today = date(2025, 12, 24) # Today is 24/12/2025
        
        # Mock data for tenants
        mock_tenants_data = {
            "company_id_1": {
                "active": {
                    "tenant_id_rental_1": {
                        "email": "rental1@example.com",
                        "mobileNumber": "1112223333",
                        "name": "Rental Tenant 1"
                    },
                    "tenant_id_rental_2": {
                        "email": "rental2@example.com",
                        "mobileNumber": "4445556666",
                        "name": "Rental Tenant 2"
                    },
                    "tenant_id_non_rental": { # This tenant's payment should be filtered out by type
                        "email": "nonrental@example.com",
                        "mobileNumber": "7778889999",
                        "name": "Non-Rental Tenant"
                    }
                }
            }
        }

        # Mock data for statistics
        mock_statistics_data = {
            "company_id_1": {
                "paymentTracking": {
                    "pending": {
                        "payment_id_rental_A": { # Tenant 1, Due exactly 7 days, rental
                            "amount": 1000,
                            "dueDate": "31/12/2025", 
                            "paymentType": 0, 
                            "tenantId": "tenant_id_rental_1",
                            "tenantName": "Rental Tenant 1",
                            "propertyName": "Property A"
                        },
                        "payment_id_rental_B": { # Tenant 1, Due exactly 7 days, rental (second unit)
                            "amount": 1200,
                            "dueDate": "31/12/2025", 
                            "paymentType": 0, 
                            "tenantId": "tenant_id_rental_1",
                            "tenantName": "Rental Tenant 1",
                            "propertyName": "Property B"
                        },
                        "payment_id_rental_C": { # Tenant 2, Due exactly 7 days, rental
                            "amount": 1500,
                            "dueDate": "31/12/2025", 
                            "paymentType": 0, 
                            "tenantId": "tenant_id_rental_2",
                            "tenantName": "Rental Tenant 2",
                            "propertyName": "Property C"
                        },
                        "payment_id_non_rental_X": { # Non-rental, should be excluded
                            "amount": 500,
                            "dueDate": "31/12/2025", 
                            "paymentType": 1, 
                            "tenantId": "tenant_id_non_rental",
                            "tenantName": "Non-Rental Tenant",
                            "propertyName": "Property X"
                        },
                        "payment_id_rental_wrong_date": { # Rental, wrong date, should be excluded
                            "amount": 2000,
                            "dueDate": "28/12/2025",
                            "paymentType": 0,
                            "tenantId": "tenant_id_rental_1",
                            "tenantName": "Rental Tenant 1",
                            "propertyName": "Property D"
                        }
                    }
                }
            }
        }

        with patch('functions.logic.notification_logic.date') as mock_date:
            mock_date.today.return_value = mock_today
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

            grouped_rentals = get_due_rentals_by_tenant(mock_statistics_data, mock_tenants_data, 7)
            
            self.assertIsInstance(grouped_rentals, dict)
            self.assertEqual(len(grouped_rentals), 2) # Expect 2 tenants with due rentals

            # Assert tenant_id_rental_1's rentals
            self.assertIn('tenant_id_rental_1', grouped_rentals)
            tenant1_data = grouped_rentals['tenant_id_rental_1']
            self.assertEqual(tenant1_data['tenant_info']['name'], 'Rental Tenant 1')
            self.assertEqual(tenant1_data['tenant_info']['email'], 'rental1@example.com')
            self.assertEqual(len(tenant1_data['due_rentals']), 2) # Expect two due rentals for this tenant

            # Verify individual rentals for tenant 1
            rental_props = [r['property_name'] for r in tenant1_data['due_rentals']]
            self.assertIn('Property A', rental_props)
            self.assertIn('Property B', rental_props)
            
            # Assert tenant_id_rental_2's rentals
            self.assertIn('tenant_id_rental_2', grouped_rentals)
            tenant2_data = grouped_rentals['tenant_id_rental_2']
            self.assertEqual(tenant2_data['tenant_info']['name'], 'Rental Tenant 2')
            self.assertEqual(tenant2_data['tenant_info']['email'], 'rental2@example.com')
            self.assertEqual(len(tenant2_data['due_rentals']), 1) # Expect one due rental for this tenant
            self.assertEqual(tenant2_data['due_rentals'][0]['property_name'], 'Property C')

            # Assert non-rental payments are not included
            self.assertNotIn('tenant_id_non_rental', grouped_rentals)

    def test_get_payments_to_move_to_due_soon(self):
        mock_today = date(2025, 12, 24) # Today is 24/12/2025

        mock_statistics_data = {
            "company_id_1": {
                "paymentTracking": {
                    "pending": {
                        "payment_id_rental_A": { # Due exactly 7 days, rental - should be included
                            "amount": 1000,
                            "dueDate": "31/12/2025", 
                            "paymentType": 0, 
                            "tenantId": "tenant_id_rental_1",
                            "tenantName": "Rental Tenant 1",
                            "propertyName": "Property A"
                        },
                        "payment_id_non_rental_X": { # Due exactly 7 days, non-rental - should be included
                            "amount": 500,
                            "dueDate": "31/12/2025", 
                            "paymentType": 1, 
                            "tenantId": "tenant_id_non_rental",
                            "tenantName": "Non-Rental Tenant",
                            "propertyName": "Property X"
                        },
                        "payment_id_rental_old": { # Wrong date, should be excluded
                            "amount": 2000,
                            "dueDate": "28/12/2025",
                            "paymentType": 0,
                            "tenantId": "tenant_id_rental_1",
                            "tenantName": "Rental Tenant 1",
                            "propertyName": "Property D"
                        }
                    }
                }
            }
        }

        with patch('functions.logic.notification_logic.date') as mock_date:
            mock_date.today.return_value = mock_today
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

            payments_to_move = get_payments_to_move_to_due_soon(mock_statistics_data, 7)

            self.assertIsInstance(payments_to_move, list)
            self.assertEqual(len(payments_to_move), 2) # Expect 2 payments to move

            # Verify contents of payments_to_move
            payment_ids = [p['payment_id'] for p in payments_to_move]
            self.assertIn("payment_id_rental_A", payment_ids)
            self.assertIn("payment_id_non_rental_X", payment_ids)
            self.assertNotIn("payment_id_rental_old", payment_ids)
            
            # Check a specific payment's details
            rental_payment = next(p for p in payments_to_move if p['payment_id'] == 'payment_id_rental_A')
            self.assertEqual(rental_payment['company_id'], 'company_id_1')
            self.assertEqual(rental_payment['payment_details']['amount'], 1000)
            self.assertEqual(rental_payment['payment_details']['paymentType'], 0)


    def test_get_due_rentals_by_landlord(self):
        mock_today = date(2025, 12, 24) # Today is 24/12/2025

        mock_companies_data = {
            "company_id_1": {"contactEmail": "landlord1@example.com"},
            "company_id_2": {"contactEmail": "landlord2@example.com"}
        }

        mock_tenants_data = {
            "company_id_1": {
                "active": {
                    "tenant_id_rental_A": {"email": "tenantA@example.com"},
                    "tenant_id_non_rental_B": {"email": "tenantB@example.com"}
                }
            },
            "company_id_2": {
                "active": {
                    "tenant_id_rental_C": {"email": "tenantC@example.com"}
                }
            }
        }

        mock_statistics_data = {
            "company_id_1": {
                "paymentTracking": {
                    "pending": {
                        "payment_id_rental_A": {
                            "amount": 1000,
                            "dueDate": "31/12/2025", # Exactly 7 days from today
                            "paymentType": 0, # Rental
                            "tenantId": "tenant_id_rental_A",
                            "tenantName": "Tenant A",
                            "propertyName": "Property A"
                        },
                        "payment_id_non_rental_B": {
                            "amount": 500,
                            "dueDate": "31/12/2025", # Exactly 7 days from today
                            "paymentType": 1, # Non-rental - should be excluded
                            "tenantId": "tenant_id_non_rental_B",
                            "tenantName": "Tenant B",
                            "propertyName": "Property B"
                        },
                        "payment_id_rental_old": { # Should be excluded
                            "amount": 700,
                            "dueDate": "28/12/2025", 
                            "paymentType": 0,
                            "tenantId": "tenant_id_rental_A",
                            "tenantName": "Tenant A Old",
                            "propertyName": "Property A Old"
                        }
                    }
                }
            },
            "company_id_2": {
                "paymentTracking": {
                    "pending": {
                        "payment_id_rental_C": {
                            "amount": 1500,
                            "dueDate": "31/12/2025", # Exactly 7 days from today
                            "paymentType": 0, # Rental
                            "tenantId": "tenant_id_rental_C",
                            "tenantName": "Tenant C",
                            "propertyName": "Property C"
                        },
                        "payment_id_rental_wrong_date_C": { # Should be excluded
                            "amount": 1200,
                            "dueDate": "30/12/2025", 
                            "paymentType": 0,
                            "tenantId": "tenant_id_rental_C",
                            "tenantName": "Tenant C Wrong Date",
                            "propertyName": "Property C Wrong Date"
                        }
                    }
                }
            }
        }

        with patch('functions.logic.notification_logic.date') as mock_date:
            mock_date.today.return_value = mock_today
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

            landlord_due_rentals = get_due_rentals_by_landlord(mock_statistics_data, mock_tenants_data, mock_companies_data, 7)

            self.assertIsInstance(landlord_due_rentals, dict)
            self.assertEqual(len(landlord_due_rentals), 2) # Expect 2 landlords with due rentals

            # Assert landlord1@example.com's rentals
            self.assertIn("landlord1@example.com", landlord_due_rentals)
            landlord1_rentals = landlord_due_rentals["landlord1@example.com"]
            self.assertEqual(len(landlord1_rentals), 1) # Only one rental (payment_id_rental_A)
            self.assertEqual(landlord1_rentals[0]['tenant_name'], "Tenant A")
            self.assertEqual(landlord1_rentals[0]['amount'], 1000)
            self.assertEqual(landlord1_rentals[0]['due_date'], '31/12/2025')

            # Assert landlord2@example.com's rentals
            self.assertIn("landlord2@example.com", landlord_due_rentals)
            landlord2_rentals = landlord_due_rentals["landlord2@example.com"]
            self.assertEqual(len(landlord2_rentals), 1) # Only one rental (payment_id_rental_C)
            self.assertEqual(landlord2_rentals[0]['tenant_name'], "Tenant C")
            self.assertEqual(landlord2_rentals[0]['amount'], 1500)
            self.assertEqual(landlord2_rentals[0]['due_date'], '31/12/2025')

            # Assert non-rental payment is not included
            for rentals in landlord_due_rentals.values():
                for rental in rentals:
                    self.assertNotIn("Non-Rental Tenant", rental['tenant_name'])
                    self.assertNotIn("Tenant A Old", rental['tenant_name'])
                    self.assertNotIn("Tenant C Wrong Date", rental['tenant_name'])


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
        self.patch_get_companies = patch('functions.main.get_all_companies') # Add mock for get_all_companies
        self.patch_move_payment_to_due = patch('functions.main.move_payment_to_due')
        self.patch_get_payments_to_move_to_due_soon = patch('functions.main.get_payments_to_move_to_due_soon')
        
        self.mock_enqueue = self.patch_enqueue.start()
        self.mock_get_tenants = self.patch_get_tenants.start()
        self.mock_get_statistics = self.patch_get_statistics.start()
        self.mock_get_companies = self.patch_get_companies.start() # Start the mock
        self.mock_move_payment_to_due = self.patch_move_payment_to_due.start()
        self.mock_get_payments_to_move_to_due_soon = self.patch_get_payments_to_move_to_due_soon.start()


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

    def test_main_triggers_tenant_notifications(self): # Renamed function
        statistics_data = copy.deepcopy(self.full_db_data["HomeHive"]["PropertyManagement"]["Statistics"])
        tenants_data = copy.deepcopy(self.full_db_data["HomeHive"]["PropertyManagement"]["Tenants"])
        
        # We need to mock these to control the return values precisely
        self.mock_get_statistics.return_value = statistics_data
        self.mock_get_tenants.return_value = tenants_data
        self.mock_get_companies.return_value = { # Use actual company IDs and emails from test_db.json
            "-OTi3TKQ16jieuDen2Pv": {"contactEmail": "support@wachilamaka.co.zm"},
            "-OTlPNCoFjq8k_XsMqw2": {"contactEmail": "kalumbabwale@gmail.com"},
            "-OTwq4TeVXxvt9GBXWe1": {"contactEmail": "Chombasikasote@yahoo.com"},
            "-OU4R7yDY7uGpYed6j0B": {"contactEmail": "chipusiles@gmail.com"},
            "-OXCgbwyw1s1xQ8bAPpu": {"contactEmail": "chipusiles@gmail.com"}
        }
        
        # Mock dueSoon payments to be empty for this test
        self.mock_get_payments_to_move_to_due_soon.return_value = []
        
        mock_event = MockEvent()

        with self.app.app_context():
            with patch('functions.logic.notification_logic.date') as mock_date_logic, \
                 patch('functions.main.get_due_rentals_by_tenant') as mock_get_due_rentals_by_tenant: # Patch new function
                mock_date_logic.today.return_value = date(2025, 12, 24) # Set a fixed date for the test
                mock_date_logic.side_effect = lambda *args, **kw: date(*args, **kw) # Allow normal date constructor

                # Mock to ensure enqueue is called with the expected tenant_info
                # This should be a grouped structure now
                mock_get_due_rentals_by_tenant.return_value = {
                    'tenant_id_1': {
                        'tenant_info': {
                            'tenant_id': 'tenant_id_1',
                            'name': 'Tenant One',
                            'email': 'tenant1@example.com',
                            'mobileNumber': '111',
                        },
                        'due_rentals': [
                            {
                                'dueDate': '31/12/2025',
                                'rent_amount': 1000,
                                'property_name': 'Property A',
                                'payment_id': 'payment_A',
                                'company_id': 'company_id_1' # Added company_id
                            },
                            {
                                'dueDate': '31/12/2025',
                                'rent_amount': 500,
                                'property_name': 'Property B',
                                'payment_id': 'payment_B',
                                'company_id': 'company_id_1' # Added company_id
                            }
                        ]
                    }
                } 
                notification_handler(mock_event)
        
        mock_get_due_rentals_by_tenant.assert_called_once_with(statistics_data, tenants_data, 7)
        self.mock_get_payments_to_move_to_due_soon.assert_called_once_with(statistics_data, 7)
        self.mock_move_payment_to_due.assert_not_called() # No payments to move
        # enqueue_notification_tasks should be called with a list of the values from the grouped dict
        self.mock_enqueue.assert_called_once_with(list(mock_get_due_rentals_by_tenant.return_value.values()))



    @patch('functions.main.get_all_companies')
    @patch('functions.main.get_due_rentals_by_landlord')
    @patch('functions.main.send_landlord_summary_email')
    def test_main_function_triggers_landlord_notifications(self, mock_send_landlord_summary_email, mock_get_due_rentals_by_landlord, mock_get_all_companies):
        statistics_data = copy.deepcopy(self.full_db_data["HomeHive"]["PropertyManagement"]["Statistics"])
        tenants_data = copy.deepcopy(self.full_db_data["HomeHive"]["PropertyManagement"]["Tenants"])
        companies_data = {
            "company_id_1": {"contactEmail": "landlord1@example.com"},
            "company_id_2": {"contactEmail": "landlord2@example.com"}
        }
        
        self.mock_get_statistics.return_value = statistics_data
        self.mock_get_tenants.return_value = tenants_data
        mock_get_all_companies.return_value = companies_data

        mock_landlord_rentals = {
            "landlord1@example.com": [
                {'tenant_name': 'Tenant A', 'property_name': 'Property A', 'amount': 1000, 'due_date': '31/12/2025'}
            ],
            "landlord2@example.com": [
                {'tenant_name': 'Tenant C', 'property_name': 'Property C', 'amount': 1500, 'due_date': '31/12/2025'}
            ]
        }
        mock_get_due_rentals_by_landlord.return_value = mock_landlord_rentals
        
        # Mock dueSoon payments to be empty for this test
        self.mock_get_payments_to_move_to_due_soon.return_value = []

        mock_event = MockEvent()

        with self.app.app_context():
            with patch('functions.logic.notification_logic.date') as mock_date_logic, \
                 patch('functions.main.get_due_rentals_by_tenant') as mock_get_due_rentals_by_tenant: # Patch new function
                mock_date_logic.today.return_value = date(2025, 12, 24)
                mock_date_logic.side_effect = lambda *args, **kw: date(*args, **kw)

                mock_get_due_rentals_by_tenant.return_value = {} # No tenant reminders for this test

                notification_handler(mock_event)
        
        mock_get_all_companies.assert_called_once()
        mock_get_due_rentals_by_landlord.assert_called_once_with(
            statistics_data, tenants_data, companies_data, 7
        )
        self.mock_get_payments_to_move_to_due_soon.assert_called_once_with(statistics_data, 7)
        self.mock_move_payment_to_due.assert_not_called() # No payments to move
        self.assertEqual(mock_send_landlord_summary_email.call_count, 2)
        mock_send_landlord_summary_email.assert_any_call(
            "landlord1@example.com", mock_landlord_rentals["landlord1@example.com"], ANY # ANY for template_env
        )
        mock_send_landlord_summary_email.assert_any_call(
            "landlord2@example.com", mock_landlord_rentals["landlord2@example.com"], ANY # ANY for template_env
        )

class TestNotificationWorker(unittest.TestCase):
    @patch.dict(os.environ, {
        "SENDER_EMAIL": "test@example.com", 
        "TESTING_MODE": "false" # Explicitly disable testing mode
    })
    @patch('functions.services.email_service.boto3.client')
    @patch('functions.services.email_service.access_secret_version')
    def test_send_tenant_summary_email_success(self, mock_access_secret_version, mock_boto_client):
        mock_access_secret_version.side_effect = ["mock_aws_access_key", "mock_aws_secret_key"]
        mock_ses_instance = mock_boto_client.return_value
        mock_ses_instance.send_raw_email.return_value = {} # send_raw_email is now always used
        
        tenant_consolidated_info = {
            'tenant_info': { # Nested tenant_info
                'tenant_id': 'test-tenant-1',
                'name': 'Test Tenant',
                'email': 'recipient@example.com', 
                'mobileNumber': '1234567890',
            },
            'due_rentals': [
                {
                    'dueDate': '31/12/2025',
                    'rent_amount': 1000,
                    'property_name': 'Test Property A',
                    'payment_id': 'payment-A'
                },
                {
                    'dueDate': '31/12/2025',
                    'rent_amount': 500,
                    'property_name': 'Test Property B',
                    'payment_id': 'payment-B'
                }
            ]
        }
        
        with patch('functions.main.template_env') as mock_template_env, \
             patch('functions.services.invoice_service.create_invoice_pdf') as mock_create_invoice_pdf:
            mock_create_invoice_pdf.return_value = b'mock_pdf_data'
            mock_template_env.get_template.return_value.render.return_value = 'mock_html_body'

            success = send_tenant_summary_email(tenant_consolidated_info, mock_template_env, invoice_pdf=b'mock_pdf_data')

            self.assertTrue(success)
            mock_ses_instance.send_raw_email.assert_called_once()
            call_args = mock_ses_instance.send_raw_email.call_args[1]
            self.assertEqual(call_args['Destinations'], ['recipient@example.com'])
            
            mock_template_env.get_template.assert_called_with('tenant_summary_email.html')
            mock_template_env.get_template.return_value.render.assert_called_with(
                name='Test Tenant', 
                due_rentals=tenant_consolidated_info['due_rentals']
            )

    @patch.dict(os.environ, {
        "SENDER_EMAIL": "landlord@example.com", 
        "TESTING_MODE": "false"
    })
    @patch('functions.services.email_service.boto3.client')
    @patch('functions.services.email_service.access_secret_version')
    def test_send_landlord_summary_email_success(self, mock_access_secret_version, mock_boto_client):
        mock_access_secret_version.side_effect = ["mock_aws_access_key", "mock_aws_secret_key"]
        mock_ses_instance = mock_boto_client.return_value
        mock_ses_instance.send_raw_email.return_value = {}

        landlord_email = "landlord@example.com"
        due_rentals_list = [
            {
                'tenant_name': 'Tenant A',
                'property_name': 'Property A',
                'amount': 1000,
                'due_date': '28/12/2025',
            },
            {
                'tenant_name': 'Tenant C',
                'property_name': 'Property C',
                'amount': 1500,
                'due_date': '30/12/2025',
            },
        ]
        
        with patch('functions.main.template_env') as mock_template_env:
            mock_template_env.get_template.return_value.render.return_value = 'mock_landlord_html_body'
            
            success = send_landlord_summary_email(landlord_email, due_rentals_list, mock_template_env)

            self.assertTrue(success)
            mock_ses_instance.send_raw_email.assert_called_once()
            call_args = mock_ses_instance.send_raw_email.call_args[1]
            self.assertEqual(call_args['Destinations'], ['landlord@example.com'])
            
            # Verify subject and body content (simplified check)
            raw_message = call_args['RawMessage']['Data']
            self.assertIn("Subject: Upcoming Rental Payments Due", raw_message)
            self.assertIn("mock_landlord_html_body", raw_message)
            mock_template_env.get_template.assert_called_with('landlord_reminder_email.html')
            mock_template_env.get_template.return_value.render.assert_called_with(due_rentals=due_rentals_list)

if __name__ == '__main__':
    unittest.main()
