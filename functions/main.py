from firebase_functions import scheduler_fn, https_fn
from firebase_functions.options import set_global_options
from firebase_admin import initialize_app, storage, db
import firebase_admin # Added import
import logging
import os 
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
from services.receipt_service import generate_receipt_pdf


# Set up a module-level logger
log = logging.getLogger(__name__)

# Global Firebase app initialization, including Realtime Database URL
# firebase_options = {'databaseURL': os.environ.get('FIREBASE_DATABASE_URL')}
try:
    firebase_admin.get_app()
except ValueError:
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
    cloud_storage_path = upload_to_storage(invoice_pdf_bytes, id_number, invoice_number, file_type="invoices")
    if not cloud_storage_path:
        log.error(f"Failed to upload invoice PDF for tenant {tenant_id_for_logging}.")
        return https_fn.Response("Failed to upload invoice PDF.", status=500)

    # --- Store invoice info in the payment node ---
    # We will use the first due rental's info to identify the payment node
    if not tenant_consolidated_info.get('due_rentals'):
        log.error(f"No due rentals found for tenant {tenant_id_for_logging}. Cannot store invoice info.")
        return https_fn.Response("No due rentals for invoice.", status=400)

    first_rental = tenant_consolidated_info['due_rentals'][0]
    company_id_for_payment = first_rental.get('company_id')
    payment_id_for_payment = first_rental.get('payment_id')
    tenant_id_for_payment = tenant_info.get('tenant_id') # Use the tenantId from tenant_info

    if not company_id_for_payment or not payment_id_for_payment or not tenant_id_for_payment:
        log.error(f"Missing identifiers for payment node for tenant {tenant_id_for_logging}. Cannot store invoice info.")
        return https_fn.Response("Missing payment identifiers.", status=400)

    rt_db_path = f"HomeHive/PropertyManagement/Accounts/{company_id_for_payment}/{tenant_id_for_payment}/payments/{payment_id_for_payment}/invoice"
    ref = db.reference(rt_db_path)
    ref.set({
        'cloudStoragePath': cloud_storage_path,
        'invoice_number': invoice_number,
        'created_at': datetime.now().isoformat()
    })
    log.info(f"Stored invoice info in RTDB at: {rt_db_path}")

    # Construct the URL to the get_invoice Cloud Function
    cloud_function_base_url = os.environ.get('CLOUD_FUNCTION_BASE_URL', 'https://us-central1-homehive-8c7d4.cloudfunctions.net')
    invoice_url = f"{cloud_function_base_url}/get_invoice?companyId={company_id_for_payment}&tenantId={tenant_id_for_payment}&paymentId={payment_id_for_payment}"


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
    It takes companyId, tenantId, and paymentId as query parameters to locate
    the invoice information in Realtime Database.
    """
    company_id = req.args.get('companyId')
    tenant_id = req.args.get('tenantId')
    payment_id = req.args.get('paymentId')

    if not company_id or not tenant_id or not payment_id:
        log.error("Missing companyId, tenantId, or paymentId query parameters for get_invoice.")
        return https_fn.Response("Missing identifiers.", status=400)

    try:
        rt_db_path = f"HomeHive/PropertyManagement/Accounts/{company_id}/{tenant_id}/payments/{payment_id}/invoice"
        ref = db.reference(rt_db_path)
        data = ref.get()

        if not data:
            log.warning(f"Invoice data not found in RTDB at: {rt_db_path}")
            return https_fn.Response("Invoice not found.", status=404)
        
        cloud_storage_path = data.get('cloudStoragePath')
        invoice_number = data.get('invoice_number') # Not strictly needed here, but good for logs

        if not cloud_storage_path:
            log.error(f"Missing cloudStoragePath in RTDB at: {rt_db_path}")
            return https_fn.Response("Invoice path not found.", status=500)
        
        # Now, retrieve the PDF content directly from Cloud Storage
        bucket = storage.bucket()
        blob = bucket.blob(cloud_storage_path) # Use the path directly from RTDB

        if not blob.exists():
            log.error(f"Invoice PDF not found in storage at: {cloud_storage_path}")
            return https_fn.Response("Invoice file not found in storage.", status=404)

        pdf_content = blob.download_as_bytes()
        
        log.info(f"Streaming invoice PDF for payment {payment_id} directly to client.")
        return https_fn.Response(pdf_content, headers={"Content-Type": "application/pdf"}, status=200)

    except Exception as e:
        log.error(f"Error in get_invoice for payment {payment_id}: {e}")
        return https_fn.Response("An error occurred.", status=500)


@https_fn.on_request()
def generate_receipt(req: https_fn.Request) -> https_fn.Response:
    """
    HTTP-triggered function that generates a receipt, stores it, and returns the URL.
    """
    try:
        data = req.get_json(silent=True)
        if not data:
            log.error("No data in request body.")
            return https_fn.Response("No data received", status=400)

        # Generate a unique name for the receipt
        receipt_number = str(uuid.uuid4())
        
        # Generate the PDF
        pdf_bytes = generate_receipt_pdf(data)
        
        # Upload to storage
        id_number = data.get("id_number")
        if not id_number:
            log.error("Missing id_number in request.")
            return https_fn.Response("Missing id_number.", status=400)
            
        file_path = upload_to_storage(pdf_bytes, id_number, receipt_number, file_type="receipts")
        
        if file_path:
            # Construct the URL to the get_receipt Cloud Function
            cloud_function_base_url = os.environ.get('CLOUD_FUNCTION_BASE_URL', 'https://us-central1-homehive-8c7d4.cloudfunctions.net')
            receipt_url = f"{cloud_function_base_url}/get_receipt?id_number={id_number}&receipt_number={receipt_number}"
            
            return https_fn.Response(receipt_url, status=200)
        else:
            log.error("Failed to upload receipt.")
            return https_fn.Response("Failed to upload receipt.", status=500)

    except Exception as e:
        log.error(f"An unexpected error occurred in generate_receipt: {e}")
        return https_fn.Response("An error occurred.", status=500)


@https_fn.on_request()
def get_receipt(req: https_fn.Request) -> https_fn.Response:
    """
    HTTP-triggered function that retrieves a receipt PDF from Google Cloud Storage
    and streams its content directly to the client.
    """
    id_number = req.args.get('id_number')
    receipt_number = req.args.get('receipt_number')

    if not id_number or not receipt_number:
        log.error("Missing id_number or receipt_number query parameters for get_receipt.")
        return https_fn.Response("Missing identifiers.", status=400)

    try:
        file_path = f"Tenants/{id_number}/receipts/{receipt_number}.pdf"
        
        # Now, retrieve the PDF content directly from Cloud Storage
        bucket = storage.bucket()
        blob = bucket.blob(file_path)

        if not blob.exists():
            log.error(f"Receipt PDF not found in storage at: {file_path}")
            return https_fn.Response("Receipt file not found in storage.", status=404)

        pdf_content = blob.download_as_bytes()
        
        log.info(f"Streaming receipt PDF for receipt {receipt_number} directly to client.")
        return https_fn.Response(pdf_content, headers={"Content-Type": "application/pdf"}, status=200)

    except Exception as e:
        log.error(f"Error in get_receipt for receipt {receipt_number}: {e}")
        return https_fn.Response("An error occurred.", status=500)