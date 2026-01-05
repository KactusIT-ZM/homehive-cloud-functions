import json
import logging
import os
import uuid
from google.cloud import tasks_v2

# Set up a module-level logger
log = logging.getLogger(__name__)

# Cloud Tasks Constants - use environment variable to detect project
PROJECT = os.environ.get('GCP_PROJECT') or os.environ.get('GCLOUD_PROJECT') or 'homehive-dev-89916'
QUEUE = 'notification-queue'
LOCATION = 'us-central1'

def enqueue_tasks(payloads: list, target_function: str, task_name_prefix: str = "task-"):
    """
    Enqueues tasks to Cloud Tasks.
    """
    tasks_client = tasks_v2.CloudTasksClient()
    parent = tasks_client.queue_path(PROJECT, LOCATION, QUEUE)

    for payload_data in payloads:
        url = f"https://{LOCATION}-{PROJECT}.cloudfunctions.net/{target_function}"
        payload = json.dumps(payload_data)

        # Add UUID to make task name unique and avoid 409 errors
        task_name = f"{task_name_prefix}{payload_data.get('tenant_id', '')}-{payload_data.get('email_type', '')}-{uuid.uuid4().hex[:8]}"

        task = {
            "name": tasks_client.task_path(PROJECT, LOCATION, QUEUE, task_name),
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": url,
                "headers": {"Content-type": "application/json"},
                "body": payload.encode(),
            }
        }
        
        try:
            response = tasks_client.create_task(parent=parent, task=task)
            log.info(f"Created task {response.name}")
        except Exception as e:
            log.error(f"Error creating task: {e}")