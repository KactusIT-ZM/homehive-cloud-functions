import unittest
from unittest.mock import patch, MagicMock
# from firebase_functions import https_fn # No longer importing real Request
from main import generate_receipt, get_receipt
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

class TestReceipts(unittest.TestCase):

    @patch('main.enqueue_tasks')
    @patch('main.os.environ.get', return_value='https://test.com')
    @patch('main.uuid.uuid4')
    @patch('main.storage.bucket')
    @patch('main.generate_receipt_pdf')
    def test_generate_receipt_success(self, mock_generate_receipt_pdf, mock_storage_bucket, mock_uuid, mock_env_get, mock_enqueue_tasks):
        # Mocking the PDF generation
        mock_generate_receipt_pdf.return_value = b'test_pdf_content'
        mock_uuid.return_value = "test-uuid"

        # Mocking the storage
        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_storage_bucket.return_value = mock_bucket

        # Mocking the request
        req_data = {
            "tenant_name": "John Doe",
            "tenant_email": "john.doe@example.com",
            "property_name": "The Grand Estate",
            "date_paid": "2025-12-31",
            "next_payment_date": "2026-01-31",
            "amount_paid": 1500.00,
            "additional_info": [
                {"title": "Rent", "amount": 1400.00},
                {"title": "Late Fee", "amount": 100.00}
            ],
            "id_number": "12345"
        }
        req = MockRequest(json_data=req_data)

        # Call the function
        response = generate_receipt(req)

        # Assertions
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"https://test.com/get_receipt?id_number=12345&receipt_number=test-uuid")
        mock_generate_receipt_pdf.assert_called_once_with(req_data)
        mock_storage_bucket.assert_called_once()
        mock_bucket.blob.assert_called_once_with("Tenants/12345/receipts/test-uuid.pdf")
        mock_blob.upload_from_string(
            b'test_pdf_content',
            content_type='application/pdf'
        )
        mock_enqueue_tasks.assert_called_once()


    @patch('main.storage.bucket')
    def test_get_receipt_success(self, mock_storage_bucket):
        # Mocking the storage
        mock_blob = MagicMock()
        mock_blob.exists.return_value = True
        mock_blob.download_as_bytes.return_value = b'test_pdf_content'
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_storage_bucket.return_value = mock_bucket

        # Mocking the request
        req_args = {"id_number": "12345", "receipt_number": "test-uuid"}
        req = MockRequest(args_data=req_args)

        # Call the function
        response = get_receipt(req)

        # Assertions
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'test_pdf_content')
        self.assertEqual(response.headers['Content-Type'], 'application/pdf')
        mock_storage_bucket.assert_called_once()
        mock_bucket.blob.assert_called_once_with("Tenants/12345/receipts/test-uuid.pdf")
        mock_blob.exists.assert_called_once()
        mock_blob.download_as_bytes.assert_called_once()


if __name__ == '__main__':
    unittest.main()
