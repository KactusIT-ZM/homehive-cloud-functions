import logging
from firebase_admin import storage
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

def upload_to_storage(file_bytes: bytes, id_number: str, invoice_number: str) -> bool:
    """
    Uploads a file to Firebase Storage.
    Returns True if successful, False otherwise.
    """
    try:
        bucket = storage.bucket()
        
        # Create a path in the bucket, e.g., "Tenants/id_number/invoices/invoice_number.pdf"
        file_path = f"Tenants/{id_number}/invoices/{invoice_number}.pdf"
        blob = bucket.blob(file_path)

        # Upload the file from bytes
        blob.upload_from_string(
            file_bytes,
            content_type='application/pdf'
        )
        
        log.info(f"Successfully uploaded invoice to {file_path}.")
        return True

    except Exception as e:
        log.error(f"Error uploading to Firebase Storage: {e}")
        return False
