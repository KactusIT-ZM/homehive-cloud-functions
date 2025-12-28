import json
import logging
from google.cloud import tasks_v2

# Set up a module-level logger
log = logging.getLogger(__name__)

# Cloud Tasks Constants
PROJECT = 'homehive-8c7d4'
QUEUE = 'notification-queue'
LOCATION = 'us-central1'

def enqueue_notification_tasks(due_tenants: list):
    """
    Enqueues tasks to Cloud Tasks to send notifications to tenants.
    """
    tasks_client = tasks_v2.CloudTasksClient()
    parent = tasks_client.queue_path(PROJECT, LOCATION, QUEUE)

    for tenant_info in due_tenants:
        url = f"https://{LOCATION}-{PROJECT}.cloudfunctions.net/send_notification_worker"
        payload = json.dumps(tenant_info)
        
        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": url,
                "headers": {"Content-type": "application/json"},
                "body": payload.encode(),
            }
        }
        
        try:
            response = tasks_client.create_task(parent=parent, task=task)
            log.info(f"Created task {response.name} for tenant {tenant_info['tenant_info']['tenant_id']}")
        except Exception as e:
            log.error(f"Error creating task for tenant {tenant_info['tenant_info']['tenant_id']}: {e}")