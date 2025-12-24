import os
import logging
from google.cloud import secretmanager
from google.api_core.exceptions import PermissionDenied

# Set up a module-level logger
log = logging.getLogger(__name__)

# Initialize Secret Manager client
secret_client = secretmanager.SecretManagerServiceClient()

def access_secret_version(secret_id, version_id="latest"):
    """Access the payload for the given secret version if one exists.
    
    The version can be a version number or the string "latest".
    """
    try:
        project_id = os.environ.get('GCLOUD_PROJECT') # Firebase automatically sets this
        if not project_id:
            # Fallback for local testing if GCLOUD_PROJECT is not set
            # Replace with your actual project ID for local testing if needed
            project_id = "homehive-8c7d4" 
            log.warning(f"GCLOUD_PROJECT not found, using default {project_id} for local secret access.")

        name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
        response = secret_client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8").strip()
    except PermissionDenied as e:
        log.error(f"Permission denied when accessing secret '{secret_id}': {e}")
        log.error(f"Please ensure the service account has the 'Secret Manager Secret Accessor' role for secret '{secret_id}'.")
        return None
    except Exception as e:
        log.error(f"Unexpected error accessing secret '{secret_id}': {e}")
        return None
