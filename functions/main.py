from firebase_functions import scheduler_fn, https_fn
from firebase_functions.options import set_global_options
from firebase_admin import initialize_app
import logging
import os 

from services.db_service import (
    get_all_tenants, get_all_statistics, 
    move_payment_to_overdue, 
    get_all_companies, move_payment_to_due
)
from logic.notification_logic import (
    get_due_rentals_by_tenant, 
    get_payments_to_move_to_overdue, 
    get_due_rentals_by_landlord, 
    get_payments_to_move_to_due, 
    get_payments_to_move_from_due_to_overdue
)
from services.cloud_tasks_service import enqueue_notification_tasks
from utils.template_renderer import template_env
from services.email_service import (
    send_tenant_summary_email, 
    send_landlord_summary_email
)
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
    companies = get_all_companies() # Fetch company data

    if statistics and tenants and companies:
        grouped_due_rentals_by_tenant = get_due_rentals_by_tenant(statistics, tenants, days_window)
        payments_to_move_to_due = get_payments_to_move_to_due(statistics, days_window) # Get payments for dueSoon
        payments_to_move_to_overdue = get_payments_to_move_to_overdue(statistics)
        landlord_due_rentals = get_due_rentals_by_landlord(statistics, tenants, companies, days_window)

        if grouped_due_rentals_by_tenant:
            log.info(f"Found {len(grouped_due_rentals_by_tenant)} tenants with rent due exactly {days_window} days from now:")
            # Enqueue each tenant's consolidated reminder as a single task
            enqueue_notification_tasks(list(grouped_due_rentals_by_tenant.values()))
            for tenant_id, tenant_data in grouped_due_rentals_by_tenant.items():
                log.info(f"  - Enqueued consolidated reminder for Tenant ID: {tenant_id}, Name: {tenant_data['tenant_info']['name']}")
        else:
            log.info(f"No tenants found with rent due exactly {days_window} days from now.")

        if landlord_due_rentals:
            log.info(f"Found {len(landlord_due_rentals)} landlords with due rentals exactly {days_window} days from now.")
            for landlord_email, rentals_list in landlord_due_rentals.items():
                log.info(f"  - Sending summary email to landlord {landlord_email} for {len(rentals_list)} due rentals.")
                send_landlord_summary_email(landlord_email, rentals_list, template_env)
        else:
            log.info("No landlords found with due rentals for notification.")
        
        # --- Move payments to due ---
        if payments_to_move_to_due:
            log.warning(f"Found {len(payments_to_move_to_due)} payments to move to due:")
            for payment in payments_to_move_to_due:
                log.warning(f"  - Payment: {payment['payment_id']} for company {payment['company_id']}, Due: {payment['payment_details'].get('dueDate')} (moving to dueSoon)")
                move_payment_to_due(payment['company_id'], payment['payment_id'], payment['payment_details'])
        else:
            log.info("No payments to move to dueSoon.")

        # --- Move payments to overdue (existing logic) ---
        if payments_to_move_to_overdue:
            log.warning(f"Found {len(payments_to_move_to_overdue)} payments to move to overdue:")
            for payment in payments_to_move_to_overdue:
                log.warning(f"  - Payment: {payment['payment_id']} for company {payment['company_id']}, Due: {payment['payment_details'].get('dueDate')}")
                move_payment_to_overdue(payment['company_id'], payment['payment_id'], payment['payment_details'])
        else:
            log.info("No payments to move to overdue.")

        # --- Move payments from due to overdue ---
        payments_to_move_from_due_to_overdue = get_payments_to_move_from_due_to_overdue(statistics)
        if payments_to_move_from_due_to_overdue:
            log.warning(f"Found {len(payments_to_move_from_due_to_overdue)} payments to move from due to overdue:")
            for payment in payments_to_move_from_due_to_overdue:
                log.warning(f"  - Payment: {payment['payment_id']} for company {payment['company_id']}, Due: {payment['payment_details'].get('dueDate')} (moving from due to overdue)")
                move_payment_to_overdue(payment['company_id'], payment['payment_id'], payment['payment_details'])
        else:
            log.info("No payments to move from due to overdue.")

    else:
        log.info("No statistics, tenants, or companies data found in the database. Exiting.")

@https_fn.on_request()
def send_notification_worker(req: https_fn.Request) -> https_fn.Response:
    """
    HTTP-triggered function that receives a tenant's consolidated info and sends a notification.
    """
    tenant_id_for_logging = "UNKNOWN_TENANT" # Initialize for logging
    # try:
    tenant_consolidated_info = req.get_json(silent=True)
    if not tenant_consolidated_info:
        log.error("No tenant data in request body.")
        return https_fn.Response("No data received", status=400)
    
    tenant_id_for_logging = tenant_consolidated_info.get('tenant_info', {}).get('tenant_id', "UNKNOWN_TENANT_ID_IN_PAYLOAD")

    # Fetch companies data to get landlord emails for CC
    all_companies = get_all_companies()
    cc_recipients = set() # Use a set to store unique CC emails
    
    for rental in tenant_consolidated_info.get('due_rentals', []):
        company_id = rental.get('company_id')
        if company_id and all_companies and all_companies.get(company_id):
            landlord_email = all_companies[company_id].get('contactEmail')
            if landlord_email:
                cc_recipients.add(landlord_email)

    # Create the consolidated invoice PDF
    invoice_pdf = create_invoice_pdf(tenant_consolidated_info)

    # Call the email service to send the reminder with the consolidated invoice attached
    success = send_tenant_summary_email(tenant_consolidated_info, template_env, invoice_pdf=invoice_pdf, cc_recipients=list(cc_recipients))


    if success:
        return https_fn.Response("Email sent successfully.", status=200)
    else:
        return https_fn.Response("Failed to send email.", status=500)

    # except Exception as e:
    #     log.error(f"An unexpected error occurred in send_notification_worker for tenant {tenant_id_for_logging}: {e}")
    #     return https_fn.Response("An error occurred.", status=500)