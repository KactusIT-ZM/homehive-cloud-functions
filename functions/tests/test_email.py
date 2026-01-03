import unittest
from unittest.mock import patch, MagicMock
from main import send_email_worker
from services.email_service import send_email
from utils.template_renderer import template_env
import json

# Custom Mock Request class to simulate firebase_functions.https_fn.Request
class MockRequest:
    def __init__(self, json_data=None, args_data=None):
        self._json_data = json_data
        self._args_data = args_data if args_data is not None else {}

    def get_json(self, silent=True):
        return self._json_data

    @property
    def args(self):
        return self._args_data

class TestEmail(unittest.TestCase):

    @patch('services.email_service.boto3.client')
    @patch('services.email_service.access_secret_version')
    def test_send_email_success(self, mock_access_secret_version, mock_boto_client):
        mock_access_secret_version.side_effect = ["mock_aws_access_key", "mock_aws_secret_key"]
        mock_ses_instance = mock_boto_client.return_value
        mock_ses_instance.send_raw_email.return_value = {}

        context = {
            "name": "John Doe",
            "additional_info": [
                {"title": "Rent", "amount": 1400.00},
                {"title": "Late Fee", "amount": 100.00}
            ],
            "amount_paid": 1500.00,
            "next_payment_date": "2026-01-31",
            "receipt_url": "http://example.com/receipt.pdf",
            "current_year": 2025
        }

        success = send_email(
            recipient_email="john.doe@example.com",
            subject="Test Subject",
            template_name="receipt_email.html",
            template_env=template_env,
            context=context
        )

        self.assertTrue(success)
        mock_ses_instance.send_raw_email.assert_called_once()
    
    @patch('main.send_email')
    def test_send_email_worker_success(self, mock_send_email):
        mock_send_email.return_value = True

        req_data = {
            "recipient_email": "john.doe@example.com",
            "subject": "Test Subject",
            "template_name": "receipt_email.html",
            "context": {
                "name": "John Doe",
                "additional_info": [
                    {"title": "Rent", "amount": 1400.00},
                    {"title": "Late Fee", "amount": 100.00}
                ],
                "amount_paid": 1500.00,
                "next_payment_date": "2026-01-31",
                "receipt_url": "http://example.com/receipt.pdf",
                "current_year": 2025
            }
        }
        
        req = MockRequest(json_data=req_data)

        response = send_email_worker(req)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"Email sent successfully.")
        mock_send_email.assert_called_once()

if __name__ == '__main__':
    unittest.main()
