from firebase_functions import scheduler_fn, https_fn
from firebase_functions.options import set_global_options
from firebase_admin import initialize_app, db
from datetime import datetime, date, timedelta
import os
import json
from google.cloud import tasks_v2
import boto3
import logging
import jinja2
from .constants import DATABASE_URL, TENANTS_PATH

# Set up a module-level logger
log = logging.getLogger(__name__)

# Set up Jinja2 environment
template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
template_loader = jinja2.FileSystemLoader(searchpath=template_dir)
template_env = jinja2.Environment(loader=template_loader)

set_global_options(max_instances=10)

initialize_app(options={
    'databaseURL': DATABASE_URL
})

def _flatten_tenants(tenants: dict) -> dict:
    """Creates a flattened dictionary of tenants for quick lookups."""
    return {
        tenant_id: tenant_data
        for company_tenants in tenants.values()
        for status_group in company_tenants.values()
        for tenant_id, tenant_data in status_group.items()
    }

def _get_due_notifications_for_account(tenant_id, tenant_account, all_tenants_flat, today, due_date_upper_bound) -> list:
    """Processes a single tenant account and returns a list of due notifications."""
    due_notifications = []
    if 'reminders' not in tenant_account:
        return due_notifications

    for prop_id, reminder_details in tenant_account['reminders'].items():
        if isinstance(reminder_details, dict):
            rent_due_date_str = reminder_details.get('rentDueDate')
            if not rent_due_date_str:
                continue

            try:
                due_date = datetime.strptime(rent_due_date_str, '%d/%m/%Y').date()
                if today <= due_date <= due_date_upper_bound:
                    tenant_details = all_tenants_flat.get(tenant_id)
                    if tenant_details:
                        tenant_name = f"{tenant_details.get('firstname', '')} {tenant_details.get('lastname', '')}".strip()
                        due_notifications.append({
                            'tenant_id': tenant_id,
                            'name': tenant_name, # Added tenant name
                            'email': tenant_details.get('email'),
                            'mobileNumber': tenant_details.get('mobileNumber'),
                            'dueDate': due_date.strftime('%d/%m/%Y')
                        })
            except (ValueError, TypeError):
                log.warning(f"Could not parse date '{rent_due_date_str}' for tenant {tenant_id}")
                continue
                
    return due_notifications

def get_due_tenants_for_reminders(accounts: dict, tenants: dict, days_window: int) -> list:
    """
    Identifies tenants with rent due within the configured window by processing reminders.
    """
    today = date.today()
    due_date_upper_bound = today + timedelta(days=days_window)
    all_tenants_flat = _flatten_tenants(tenants)
    
    all_due_tenants = []
    for company_accounts in accounts.values():
        for tenant_id, tenant_account in company_accounts.items():
            due_notifications = _get_due_notifications_for_account(
                tenant_id, tenant_account, all_tenants_flat, today, due_date_upper_bound
            )
            if due_notifications:
                all_due_tenants.extend(due_notifications)
                
    return all_due_tenants

def enqueue_notification_tasks(due_tenants: list):
    """
    Enqueues tasks to Cloud Tasks to send notifications to tenants.
    """
    project = 'homehive-8c7d4'
    queue = 'notification-queue'
    location = 'us-central1'
    
    tasks_client = tasks_v2.CloudTasksClient()
    parent = tasks_client.queue_path(project, location, queue)

    for tenant_info in due_tenants:
        url = f"https://{location}-{project}.cloudfunctions.net/send_notification_worker"
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
            log.info(f"Created task {response.name} for tenant {tenant_info['tenant_id']}")
        except Exception as e:
            log.error(f"Error creating task for tenant {tenant_info['tenant_id']}: {e}")

@scheduler_fn.on_schedule(
    schedule="* 7 * * *",
    timezone=scheduler_fn.Timezone("Africa/Johannesburg"),
)
def main(event: scheduler_fn.ScheduledEvent) -> None:
    """
    The main cloud function that triggers the notification process.
    """
    days_window = int(os.environ.get('DUE_DATE_WINDOW_DAYS', 7))
    
    accounts = get_all_accounts()
    tenants = get_all_tenants()

    if accounts and tenants:
        due_tenants = get_due_tenants_for_reminders(accounts, tenants, days_window)
        
        if due_tenants:
            log.info(f"Found {len(due_tenants)} tenants with rent due in the next {days_window} days:")
            for item in due_tenants:
                log.info(f"  - Tenant: {item['tenant_id']}, Due: {item['dueDate']}, Contact: {item['email'] or item['mobileNumber']}")
            
            enqueue_notification_tasks(due_tenants)
        else:
            log.info(f"No tenants found with rent due in the next {days_window} days.")
    else:
        log.info("No accounts or tenants found in the database. Exiting.")

@https_fn.on_request()
def send_notification_worker(req: https_fn.Request) -> https_fn.Response:
    """
    HTTP-triggered function that receives a tenant's info and sends a notification.
    """
    try:
        tenant_info = req.get_json(silent=True)
        if not tenant_info:
            log.error("No tenant data in request body.")
            return https_fn.Response("No data received", status=400)

        recipient_email = tenant_info.get('email')
        due_date = tenant_info.get('dueDate')
        tenant_name = tenant_info.get('name', 'Tenant') # Default to 'Tenant' if name not provided

        if not recipient_email:
            log.error(f"No email for tenant {tenant_info.get('tenant_id')}. Skipping.")
            return https_fn.Response("No email provided", status=400)
            
        aws_region = os.environ.get("AWS_REGION", "us-east-1")
        sender_email = os.environ.get("SENDER_EMAIL")

        if not sender_email:
            log.error("SENDER_EMAIL environment variable not set.")
            return https_fn.Response("Server configuration error", status=500)
        
        # --- Andon Cord / Safety Net ---
        is_testing = os.environ.get("TESTING_MODE", "true").lower() == "true"
        if is_testing:
            original_email = recipient_email
            recipient_email = "info@kactusit.com"
            log.warning(f"TESTING_MODE is active. Redirecting email from {original_email} to {recipient_email}")

        # Render the email body from the template
        template = template_env.get_template('reminder_email.txt')
        body_text = template.render(name=tenant_name, dueDate=due_date)
        
        ses_client = boto3.client('ses', region_name=aws_region)
        
        subject = "Upcoming Rent Reminder"
        
        ses_client.send_email(
            Destination={'ToAddresses': [recipient_email]},
            Message={
                'Body': {'Text': {'Charset': 'UTF-8', 'Data': body_text}},
                'Subject': {'Charset': 'UTF-8', 'Data': subject},
            },
            Source=sender_email,
        )
        
        log.info(f"Successfully sent email reminder to {recipient_email}")
        return https_fn.Response("Email sent successfully.", status=200)

    except Exception as e:
        log.error(f"An unexpected error occurred: {e}")
        return https_fn.Response("An error occurred.", status=500)


def get_all_tenants() -> dict:
    """
    Gets all tenants from the Firebase Realtime Database.
    """
    ref = db.reference(TENANTS_PATH)
    tenants = ref.get()
    return tenants if tenants else {}

def get_all_accounts() -> dict:
    """
    Gets all accounts from the Firebase Realtime Database.
    """
    ref = db.reference('/HomeHive/PropertyManagement/Accounts')
    accounts = ref.get()
    return accounts if accounts else {}
