import logging
from firebase_admin import storage
from datetime import datetime, timedelta
import os

log = logging.getLogger(__name__)

def upload_to_storage(file_bytes: bytes, id_number: str, file_name: str, file_type: str = "invoices") -> str:
    """
    Uploads a file to Firebase Storage.
    Returns the relative path to the uploaded object (e.g., "Tenants/...") if successful, None otherwise.
    """
    try:
        # Use default bucket for the current Firebase project
        bucket = storage.bucket()

        # Create a path in the bucket, e.g., "Tenants/id_number/invoices/file_name.pdf"
        file_path = f"Tenants/{id_number}/{file_type}/{file_name}.pdf"
        blob = bucket.blob(file_path)

        # Upload the file from bytes
        blob.upload_from_string(
            file_bytes,
            content_type='application/pdf'
        )
        
        log.info(f"Successfully uploaded {file_type} to {file_path}.")
        return file_path

    except Exception as e:
        log.error(f"Error uploading to Firebase Storage: {e}")
        return None
