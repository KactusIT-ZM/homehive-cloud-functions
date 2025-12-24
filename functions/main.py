from firebase_functions import scheduler_fn, https_fn
from firebase_functions.options import set_global_options
from firebase_admin import initialize_app
import logging
import os 

from services.db_service import get_all_tenants, get_all_statistics, move_payment_to_overdue
from logic.notification_logic import get_due_tenants_for_reminders, get_payments_to_move_to_overdue
from services.cloud_tasks_service import enqueue_notification_tasks
from utils.template_renderer import template_env
from services.email_service import send_reminder_email
from services.invoice_service import create_invoice_pdf

# Set up a module-level logger
log = logging.getLogger(__name__)

initialize_app()
set_global_options(max_instances=1)

@scheduler_fn.on_schedule(
    schedule="0 7 * * *",
    timezone=scheduler_fn.Timezone("Africa/Johannesburg"),
)
def main(event: scheduler_fn.ScheduledEvent) -> None:
    """
    The main cloud function that triggers the notification process.
    """
    log.info("Starting scheduled processing function.")
    days_window = int(os.environ.get('DUE_DATE_WINDOW_DAYS', 7))
    
    statistics = get_all_statistics()
    tenants = get_all_tenants()

    if statistics and tenants:
        due_tenants = get_due_tenants_for_reminders(statistics, tenants, days_window)
        payments_to_move = get_payments_to_move_to_overdue(statistics)
        
        if due_tenants:
            log.info(f"Found {len(due_tenants)} tenants with rent due in the next {days_window} days:")
            for item in due_tenants:
                log.info(f"  - Tenant (Due Soon): {item['tenant_id']}, Due: {item['dueDate']}, Contact: {item['email'] or item['mobileNumber']}")
            
            enqueue_notification_tasks(due_tenants)
        else:
            log.info(f"No tenants found with rent due in the next {days_window} days.")
        
        if payments_to_move:
            log.warning(f"Found {len(payments_to_move)} payments to move to overdue:")
            for payment in payments_to_move:
                log.warning(f"  - Payment: {payment['payment_id']} for company {payment['company_id']}, Due: {payment['payment_details'].get('dueDate')}")
                move_payment_to_overdue(payment['company_id'], payment['payment_id'], payment['payment_details'])
        else:
            log.info("No payments to move to overdue.")

    else:
        log.info("No statistics or tenants found in the database. Exiting.")

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

        # Create the invoice PDF
        invoice_pdf = create_invoice_pdf(tenant_info)

        # Call the email service to send the reminder with the invoice attached
        success = send_reminder_email(tenant_info, template_env, invoice_pdf=invoice_pdf)

        if success:
            return https_fn.Response("Email sent successfully.", status=200)
        else:
            return https_fn.Response("Failed to send email.", status=500)

    except Exception as e:
        log.error(f"An unexpected error occurred in send_notification_worker: {e}")
        return https_fn.Response("An error occurred.", status=500)