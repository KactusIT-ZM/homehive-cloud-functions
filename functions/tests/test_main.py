import json
import os
import unittest
from unittest.mock import patch, MagicMock
from flask import Flask
from datetime import date, timedelta
import copy
import logging
from functions.main import (
    main as notification_handler,
    get_all_tenants, 
    get_all_accounts, 
    get_due_tenants_for_reminders,
    enqueue_notification_tasks,
    send_notification_worker,
    _flatten_tenants,
    _get_due_notifications_for_account
)
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
        cls.accounts_data = cls.full_db_data["HomeHive"]["PropertyManagement"]["Accounts"]

    def test_flatten_tenants(self):
        flat_tenants = _flatten_tenants(self.tenants_data)
        self.assertIn('mcevbmtsrr1b3k608cm', flat_tenants)
        self.assertEqual(flat_tenants['mcevbmtsrr1b3k608cm']['email'], 'saadaq301@gmail.com')

    def test_get_due_notifications_for_account_within_window(self):
        tenant_id = 'milsdwu5nuas68mef6'
        tenant_account = self.accounts_data['-OTi3TKQ16jieuDen2Pv'][tenant_id]
        all_tenants_flat = _flatten_tenants(self.tenants_data)
        
        today = date(2025, 12, 1)
        due_date_upper_bound = today + timedelta(days=7)

        company_id = '-OTi3TKQ16jieuDen2Pv'
        prop_id = 'mcdxxilopkeeoa81mw9'
        
        test_account = copy.deepcopy(tenant_account)
        test_account['reminders'][prop_id]['rentDueDate'] = '04/12/2025'

        notifications = _get_due_notifications_for_account(
            tenant_id, test_account, all_tenants_flat, today, due_date_upper_bound
        )
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]['dueDate'], '04/12/2025')
    
    @patch('functions.main.db.reference')
    def test_get_all_tenants_success(self, mock_db_reference):
        mock_db_reference.return_value.get.return_value = self.tenants_data
        
        tenants = get_all_tenants()
        self.assertEqual(tenants, self.tenants_data)
        mock_db_reference.assert_called_with('/HomeHive/PropertyManagement/Tenants')
    
    @patch('functions.main.db.reference')
    def test_get_all_tenants_returns_empty_if_none(self, mock_db_reference):
        mock_db_reference.return_value.get.return_value = None
        tenants = get_all_tenants()
        self.assertEqual(tenants, {})
    
    @patch('functions.main.db.reference')
    def test_get_all_accounts_success(self, mock_db_reference):
        mock_db_reference.return_value.get.return_value = self.accounts_data
        
        accounts = get_all_accounts()
        self.assertEqual(accounts, self.accounts_data)
        mock_db_reference.assert_called_with('/HomeHive/PropertyManagement/Accounts')

    @patch('functions.main.db.reference')
    def test_get_all_accounts_returns_empty_if_none(self, mock_db_reference):
        mock_db_reference.return_value.get.return_value = None
        accounts = get_all_accounts()
        self.assertEqual(accounts, {})


class TestMainIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        json_file_path = os.path.join(current_dir, 'test_db.json')
        with open(json_file_path, 'r') as f:
            cls.full_db_data = json.load(f)
        cls.app = Flask(__name__)

    def setUp(self):
        self.patch_enqueue = patch('functions.main.enqueue_notification_tasks')
        self.patch_get_tenants = patch('functions.main.get_all_tenants')
        self.patch_get_accounts = patch('functions.main.get_all_accounts')
        
        self.mock_enqueue = self.patch_enqueue.start()
        self.mock_get_tenants = self.patch_get_tenants.start()
        self.mock_get_accounts = self.patch_get_accounts.start()

    def tearDown(self):
        patch.stopall()

    def test_notification_handler_flow_enqueues_task_for_due_tenant(self):
        accounts = copy.deepcopy(self.full_db_data["HomeHive"]["PropertyManagement"]["Accounts"])
        tenants = self.full_db_data["HomeHive"]["PropertyManagement"]["Tenants"]
        
        self.mock_get_accounts.return_value = accounts
        self.mock_get_tenants.return_value = tenants
        
        today = date(2025, 11, 28)
        due_date = today + timedelta(days=3)
        
        tenant_id_to_make_due = 'milsdwu5nuas68mef6'
        company_id = '-OTi3TKQ16jieuDen2Pv'
        prop_id = 'mcdxxilopkeeoa81mw9'
        accounts[company_id][tenant_id_to_make_due]['reminders'][prop_id]['rentDueDate'] = due_date.strftime('%d/%m/%Y')
        
        mock_event = MockEvent()

        with self.app.app_context():
            with patch('functions.main.date') as mock_date:
                mock_date.today.return_value = today
                notification_handler(mock_event)

        self.assertTrue(self.mock_enqueue.called)

    def test_main_no_due_tenants(self):
        self.mock_get_accounts.return_value = self.full_db_data["HomeHive"]["PropertyManagement"]["Accounts"]
        self.mock_get_tenants.return_value = self.full_db_data["HomeHive"]["PropertyManagement"]["Tenants"]
        
        mock_event = MockEvent()
        today = date(2000, 1, 1)

        with self.app.app_context():
            with patch('functions.main.date') as mock_date:
                mock_date.today.return_value = today
                with self.assertLogs('functions.main', level='INFO') as cm:
                    notification_handler(mock_event)
                    self.assertTrue(any("No tenants found" in message for message in cm.output))
        
        self.assertFalse(self.mock_enqueue.called)

    def test_main_empty_accounts(self):
        self.mock_get_accounts.return_value = {}
        self.mock_get_tenants.return_value = self.full_db_data["HomeHive"]["PropertyManagement"]["Tenants"]
        
        mock_event = MockEvent()
        with self.app.app_context():
            with self.assertLogs('functions.main', level='INFO') as cm:
                notification_handler(mock_event)
                self.assertIn("No accounts or tenants found in the database. Exiting.", cm.output[0])
        self.assertFalse(self.mock_enqueue.called)

    def test_main_empty_tenants(self):
        self.mock_get_accounts.return_value = self.full_db_data["HomeHive"]["PropertyManagement"]["Accounts"]
        self.mock_get_tenants.return_value = {}
        
        mock_event = MockEvent()
        with self.app.app_context():
            with self.assertLogs('functions.main', level='INFO') as cm:
                notification_handler(mock_event)
                self.assertIn("No accounts or tenants found in the database. Exiting.", cm.output[0])
        self.assertFalse(self.mock_enqueue.called)

class TestNotificationWorker(unittest.TestCase):
    @patch.dict(os.environ, {"SENDER_EMAIL": "test@example.com", "AWS_REGION": "us-east-1"})
    @patch('functions.main.boto3.client')
    def test_send_email_success(self, mock_boto_client):
        mock_ses_instance = mock_boto_client.return_value
        mock_ses_instance.send_email.return_value = {'MessageId': 'test-id'}
        
        tenant_info = {'tenant_id': 'test-tenant-1', 'email': 'recipient@example.com', 'dueDate': '25/12/2025'}
        mock_request = MagicMock(spec=https_fn.Request)
        mock_request.get_json.return_value = tenant_info

        response = send_notification_worker(mock_request)

        self.assertEqual(response.status_code, 200)
        mock_ses_instance.send_email.assert_called_once()

    def test_send_email_invalid_json(self):
        mock_request = MagicMock(spec=https_fn.Request)
        mock_request.get_json.return_value = None
        
        response = send_notification_worker(mock_request)
        self.assertEqual(response.status_code, 400)

if __name__ == '__main__':
    unittest.main()