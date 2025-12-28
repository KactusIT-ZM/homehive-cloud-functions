from firebase_functions import scheduler_fn, https_fn
from firebase_functions.options import set_global_options
from firebase_admin import initialize_app, storage, db
import firebase_admin # Added import
import logging
import os 
from flask import Flask, send_from_directory
import uuid
from datetime import timedelta, datetime

from services.db_service import (
    get_all_tenants, get_all_statistics, 
    move_payment_to_overdue, 
    get_all_companies, 
    move_pending_to_due, 
    get_all_accounts,
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
from services.storage_service import upload_to_storage

# Set up a module-level logger
log = logging.getLogger(__name__)

# Global Firebase app initialization, including Realtime Database URL
# firebase_options = {'databaseURL': os.environ.get('FIREBASE_DATABASE_URL')}
initialize_app() # Automatically picks up config from environment
set_global_options(max_instances=1)

# Initialize Flask app for serving static files
app = Flask(__name__, static_folder='../tenant-portal/build', static_url_path='/')

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
    accounts = get_all_accounts()

    if statistics and tenants and companies and accounts:
        grouped_due_rentals_by_tenant = get_due_rentals_by_tenant(statistics, tenants, days_window)
        payments_to_move_to_due = get_payments_to_move_to_due(statistics, days_window)
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

        # if landlord_due_rentals:
        #     log.error(f"Found {len(landlord_due_rentals)} landlords with due rentals exactly {days_window} days from now.")
        #     for landlord_email, rentals_list in landlord_due_rentals.items():
        #         log.info(f"  - Sending summary email to landlord {landlord_email} for {len(rentals_list)} due rentals.")
        #         log.error(f"Landlord email: {landlord_email}, Rentals: {rentals_list}, template_env: {template_env}")
        #         send_landlord_summary_email(landlord_email, rentals_list, template_env)
        # else:
        #     log.info("No landlords found with due rentals for notification.")
        
        # --- Move pending to due ---
        if payments_to_move_to_due:
            log.warning(f"Found {len(payments_to_move_to_due)} payments to move to due:")
            for payment in payments_to_move_to_due:
                log.warning(f"  - Payment: {payment['payment_id']} for company {payment['company_id']}, Due: {payment['payment_details'].get('dueDate')} (moving to due)")
                move_pending_to_due(payment['company_id'], payment['payment_id'], payment['payment_details'], payment['payment_details']['tenantId'])
        else:
            log.info("No payments to move to dueSoon.")

        # --- Move payments from pending to overdue ---
        if payments_to_move_to_overdue:
            log.warning(f"Found {len(payments_to_move_to_overdue)} payments to move to overdue:")
            for payment in payments_to_move_to_overdue:
                log.warning(f"  - Payment: {payment['payment_id']} for company {payment['company_id']}, Due: {payment['payment_details'].get('dueDate')}")
                move_payment_to_overdue(payment['company_id'], payment['payment_id'], payment['payment_details'], source_tracking_node='pending')
        else:
            log.info("No payments to move to overdue.")

        # --- Move payments from due to overdue ---
        payments_to_move_from_due_to_overdue = get_payments_to_move_from_due_to_overdue(statistics)
        if payments_to_move_from_due_to_overdue:
            log.warning(f"Found {len(payments_to_move_from_due_to_overdue)} payments to move from due to overdue:")
            for payment in payments_to_move_from_due_to_overdue:
                log.warning(f"  - Payment: {payment['payment_id']} for company {payment['company_id']}, Due: {payment['payment_details'].get('dueDate')} (moving from due to overdue)")
                move_payment_to_overdue(payment['company_id'], payment['payment_id'], payment['payment_details'], source_tracking_node='due')
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
    
    tenant_info = tenant_consolidated_info.get('tenant_info', {})
    tenant_id_for_logging = tenant_info.get('tenant_id', "UNKNOWN_TENANT_ID_IN_PAYLOAD")
    id_number = tenant_info.get('idNumber')

    if not id_number:
        log.error(f"Missing idNumber for tenant {tenant_id_for_logging}. Cannot upload invoice.")
        # Decide if you want to stop or continue without the PDF
        return https_fn.Response("Missing idNumber for tenant.", status=400)

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
    invoice_pdf_bytes, invoice_number = create_invoice_pdf(tenant_consolidated_info)

    # Create the consolidated invoice PDF
    invoice_pdf_bytes, invoice_number = create_invoice_pdf(tenant_consolidated_info)

    # Upload the invoice PDF to storage
    upload_success = upload_to_storage(invoice_pdf_bytes, id_number, invoice_number)
    if not upload_success:
        log.error(f"Failed to upload invoice PDF for tenant {tenant_id_for_logging}.")
        return https_fn.Response("Failed to upload invoice PDF.", status=500)

    # Create a Realtime Database client reference
    ref = db.reference('invoiceRedirects')

    # Generate a unique invoiceId for the redirect
    invoice_redirect_id = str(uuid.uuid4())

    # Store the mapping in Realtime Database
    ref.child(invoice_redirect_id).set({
        'id_number': id_number,
        'invoice_number': invoice_number,
        'created_at': datetime.now().isoformat() # Use ISO format for datetime in RTDB
    })
    log.info(f"Created Realtime Database redirect entry for invoiceId: {invoice_redirect_id}")

    # Construct the URL to the new redirect Cloud Function
    # Assuming 'get_invoice_redirect' is the name of the new function
    # The base URL for Cloud Functions can be obtained from environment variables or constructed
    cloud_function_base_url = os.environ.get('CLOUD_FUNCTION_BASE_URL', 'https://us-central1-homehive-8c7d4.cloudfunctions.net')
    invoice_url = f"{cloud_function_base_url}/get_invoice?invoiceId={invoice_redirect_id}"


    # Call the email service to send the reminder with the consolidated invoice attached
    success = send_tenant_summary_email(tenant_consolidated_info, template_env, invoice_url=invoice_url, cc_recipients=list(cc_recipients))


    if success:
        return https_fn.Response("Email sent successfully.", status=200)
    else:
        return https_fn.Response("Failed to send email.", status=500)

    # except Exception as e:
    #     log.error(f"An unexpected error occurred in send_notification_worker for tenant {tenant_id_for_logging}: {e}")
    #     return https_fn.Response("An error occurred.", status=500)

@https_fn.on_request()
def get_invoice(req: https_fn.Request) -> https_fn.Response:
    """
    HTTP-triggered function that retrieves an invoice PDF from Google Cloud Storage
    and streams its content directly to the client. This hides the direct storage
    path from the client.
    It takes an invoiceId, retrieves the actual invoice details from Realtime Database.
    """
    ref = db.reference('invoiceRedirects')

    invoice_id = req.args.get('invoiceId')
    if not invoice_id:
        log.error("Missing invoiceId query parameter for get_invoice.")
        return https_fn.Response("Missing invoiceId.", status=400)

    try:
        data = ref.child(invoice_id).get()
        if not data:
            log.warning(f"Invoice redirect entry not found for invoiceId: {invoice_id}")
            return https_fn.Response("Invoice not found or expired.", status=404)
        
        id_number = data.get('id_number')
        invoice_number = data.get('invoice_number')

        if not id_number or not invoice_number:
            log.error(f"Incomplete redirect data for invoiceId: {invoice_id}. id_number: {id_number}, invoice_number: {invoice_number}")
            return https_fn.Response("Invalid invoice data.", status=500)
        
        # Now, retrieve the PDF content directly
        bucket = storage.bucket()
        file_path = f"Tenants/{id_number}/invoices/{invoice_number}.pdf"
        blob = bucket.blob(file_path)

        if not blob.exists():
            log.error(f"Invoice PDF not found in storage for invoiceId: {invoice_id} (Path: {file_path})")
            return https_fn.Response("Invoice file not found.", status=404)

        pdf_content = blob.download_as_bytes()
        
        log.info(f"Streaming invoiceId {invoice_id} directly to client.")
        return https_fn.Response(pdf_content, headers={"Content-Type": "application/pdf"}, status=200)

    except Exception as e:
        log.error(f"Error in get_invoice for invoiceId {invoice_id}: {e}")
        return https_fn.Response("An error occurred.", status=500)