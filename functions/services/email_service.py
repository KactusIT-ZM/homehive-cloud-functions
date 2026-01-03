import os
import boto3
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage

from .secret_manager_service import access_secret_version

# Set up a module-level logger
log = logging.getLogger(__name__)

def send_email(recipient_email: str, subject: str, template_name: str, template_env, context: dict, cc_recipients: list = None) -> bool:
    """
    Sends an email using a specified template and context.
    """
    if not recipient_email:
        log.error("No recipient email provided. Skipping email.")
        return False

    aws_region = "us-east-1"
    sender_email = os.environ.get("SENDER_EMAIL", "noreply@homehive.properties")

    if not sender_email:
        log.error("SENDER_EMAIL environment variable not set.")
        return False
    
    # --- Andon Cord / Safety Net ---
    is_testing = os.environ.get("TESTING_MODE", "true").lower() == "true"
    if is_testing:
        original_email = recipient_email
        recipient_email = "info@kactusit.com"
        log.warning(f"TESTING_MODE is active. Redirecting email from {original_email} to {recipient_email}")
        if cc_recipients:
            log.warning(f"TESTING_MODE is active. Redirecting CC recipients {cc_recipients} to {recipient_email}")
            cc_recipients = [recipient_email]

    # Render the email body from the template
    template = template_env.get_template(template_name)
    html_body = template.render(**context)
    
    # Create a plain text version as a fallback
    # This is a generic fallback, you might want to customize it
    text_body = "This is an automated message from HomeHive. Please view the HTML version of this email."

    aws_access_key_id = access_secret_version("AWS_ACCESS_KEY_ID")
    aws_secret_access_key = access_secret_version("AWS_SECRET_ACCESS_KEY")

    if not aws_access_key_id or not aws_secret_access_key:
        log.error("Failed to retrieve AWS credentials from Secret Manager.")
        return False

    try:
        ses_client = boto3.client(
            'ses',
            region_name=aws_region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key
        )
        
        msg = MIMEMultipart('mixed')
        msg['Subject'] = subject
        msg['From'] = sender_email
        msg['To'] = recipient_email
        if cc_recipients:
            msg['Cc'] = ', '.join(cc_recipients)

        msg_related = MIMEMultipart('related')
        msg.attach(msg_related)
        
        msg_alternative = MIMEMultipart('alternative')
        msg_related.attach(msg_alternative)

        msg_alternative.attach(MIMEText(text_body, 'plain'))
        msg_alternative.attach(MIMEText(html_body, 'html'))
        
        # Attach the logo
        current_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.normpath(os.path.join(current_dir, '..', 'templates', 'assets', 'apple-touch-icon.png'))
        with open(logo_path, 'rb') as f:
            logo_data = f.read()
        logo = MIMEImage(logo_data, 'png')
        logo.add_header('Content-ID', '<logo>')
        msg_related.attach(logo)
        
        destinations = [recipient_email]
        if cc_recipients:
            destinations.extend(cc_recipients)

        ses_client.send_raw_email(
            Source=sender_email,
            Destinations=destinations,
            RawMessage={'Data': msg.as_string()}
        )
        
        log.info(f"Successfully sent email with subject '{subject}' to {recipient_email}")
        if cc_recipients:
            log.info(f"CC'd to: {', '.join(cc_recipients)}")
        return True
    except Exception as e:
        log.error(f"An unexpected error occurred while sending email: {e}")
        return False

def send_tenant_summary_email(tenant_info: dict, template_env, invoice_url: str = None, cc_recipients: list = None) -> bool:
    """
    Sends a consolidated rent reminder email to the tenant, summarizing multiple due rentals.
    Optionally, CCs a list of recipients (e.g., landlord).
    Returns True if successful, False otherwise.
    """
    tenant_id_for_logging = "UNKNOWN_TENANT_IN_EMAIL_SERVICE" # Initialize for logging
    try:
        tenant_details = tenant_info.get('tenant_info', {})
        recipient_email = tenant_details.get('email')
        tenant_name = tenant_details.get('name', 'Tenant')
        tenant_id_for_logging = tenant_details.get('tenant_id', "UNKNOWN_ID_FROM_PAYLOAD") # Re-assign with extracted ID
        due_rentals = tenant_info.get('due_rentals', [])

        if not recipient_email:
            log.error(f"No email for tenant {tenant_id_for_logging}. Skipping email.")
            return False
            
        aws_region = "us-east-1"
        sender_email = os.environ.get("SENDER_EMAIL", "noreply@homehive.properties")
    # ... (rest of the code)
    except Exception as e:
        log.error(f"An unexpected error occurred while sending consolidated email for tenant {tenant_id_for_logging}: {e}")
        return False

    if not sender_email:
        log.error("SENDER_EMAIL environment variable not set.")
        return False
    
    # --- Andon Cord / Safety Net ---
    is_testing = os.environ.get("TESTING_MODE", "true").lower() == "true"
    if is_testing:
        original_email = recipient_email
        recipient_email = "info@kactusit.com"
        log.warning(f"TESTING_MODE is active. Redirecting email from {original_email} to {recipient_email}")
        if cc_recipients:
            log.warning(f"TESTING_MODE is active. Redirecting CC recipients {cc_recipients} to {recipient_email}")
            cc_recipients = [recipient_email] # Redirect CCs to the test email too

    # Render the email body from the template
    template = template_env.get_template('tenant_summary_email.html')
    html_body = template.render(
        name=tenant_name, 
        due_rentals=due_rentals,
        invoice_url=invoice_url
    )
    # Create a plain text version as a fallback
    text_body = f"Hi {tenant_name},\n\nThis is a friendly reminder that multiple rent payments are due soon for the following properties:\n\n"
    for rental in due_rentals:
        text_body += f"- Property: {rental.get('property_name', 'N/A')}, Amount: ZMW {rental.get('rent_amount', 'N/A')}, Due Date: {rental.get('dueDate', 'N/A')}\n"
    if invoice_url:
        text_body += f"\nYour consolidated invoice is available here: {invoice_url}\n"
    text_body += "You can also log in to your HomeHive portal to view your statements or make payments: https://your-homehive-portal.com\n\nIf you have already made these payments or have any questions, please disregard this email or contact us directly.\n\nThank you for being a valued tenant.\n\nSincerely,\nThe HomeHive Team\n\n© 2025 HomeHive. All rights reserved.\nThis is an automated message, please do not reply."
    
    aws_access_key_id = access_secret_version("AWS_ACCESS_KEY_ID")
    aws_secret_access_key = access_secret_version("AWS_SECRET_ACCESS_KEY")

    if not aws_access_key_id or not aws_secret_access_key:
        log.error("Failed to retrieve AWS credentials from Secret Manager.")
        return False

    try:
        ses_client = boto3.client(
            'ses',
            region_name=aws_region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key
        )
        
        subject = "Reminder: Upcoming Rental Payments Due - HomeHive"

        # Create the root message and set the headers.
        msg = MIMEMultipart('mixed')
        msg['Subject'] = subject
        msg['From'] = sender_email
        msg['To'] = recipient_email
        if cc_recipients:
            msg['Cc'] = ', '.join(cc_recipients)

        # Create a 'related' part for the HTML and embedded image.
        msg_related = MIMEMultipart('related')
        msg.attach(msg_related)
        
        # Create an 'alternative' part for the plain text and HTML.
        msg_alternative = MIMEMultipart('alternative')
        msg_related.attach(msg_alternative)

        msg_alternative.attach(MIMEText(text_body, 'plain'))
        msg_alternative.attach(MIMEText(html_body, 'html'))
        
        # Attach the logo
        current_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.normpath(os.path.join(current_dir, '..', 'templates', 'assets', 'apple-touch-icon.png'))
        with open(logo_path, 'rb') as f:
            logo_data = f.read()
        logo = MIMEImage(logo_data, 'png')
        logo.add_header('Content-ID', '<logo>')
        msg_related.attach(logo)


        
        # Determine all destinations for SES
        destinations = [recipient_email]
        if cc_recipients:
            destinations.extend(cc_recipients)

        ses_client.send_raw_email(
            Source=sender_email,
            Destinations=destinations,
            RawMessage={'Data': msg.as_string()}
        )
        
        log.info(f"Successfully sent consolidated email reminder to {recipient_email}")
        if cc_recipients:
            log.info(f"CC'd to: {', '.join(cc_recipients)}")
        return True
    except Exception as e:
        log.error(f"An unexpected error occurred while sending consolidated email: {e}")
        return False

def send_landlord_summary_email(landlord_email: str, due_rentals_list: list, template_env) -> bool:
    """
    Sends a consolidated rental payment summary email to a landlord.
    Returns True if successful, False otherwise.
    """
    if not landlord_email:
        log.error("No landlord email provided. Skipping email.")
        return False

    aws_region = "us-east-1"
    sender_email = os.environ.get("SENDER_EMAIL", "noreply@homehive.properties")

    if not sender_email:
        log.error("SENDER_EMAIL environment variable not set.")
        return False
    
    # --- Andon Cord / Safety Net ---
    is_testing = os.environ.get("TESTING_MODE", "true").lower() == "true"
    if is_testing:
        original_email = landlord_email
        landlord_email = "info@kactusit.com"
        log.warning(f"TESTING_MODE is active. Redirecting landlord email from {original_email} to {landlord_email}")

    # Render the email body from the template
    template = template_env.get_template('landlord_reminder_email.html')
    html_body = template.render(due_rentals=due_rentals_list)

    # Create a plain text version (simplified, as HTML is primary)
    text_body = "Dear Landlord,\n\nThis is a summary of rental payments that are due soon for your properties:\n\n"
    for rental in due_rentals_list:
        text_body += f"- Tenant: {rental.get('tenant_name')}, Property: {rental.get('property_name')}, Amount: ZMW {rental.get('amount')}, Due Date: {rental.get('due_date')}\n"
    text_body += "\nPlease review these upcoming payments.\n\nSincerely,\nThe HomeHive Team\n\n© 2025 HomeHive. All rights reserved.\nThis is an automated message, please do not reply."
    
    aws_access_key_id = access_secret_version("AWS_ACCESS_KEY_ID")
    aws_secret_access_key = access_secret_version("AWS_SECRET_ACCESS_KEY")

    if not aws_access_key_id or not aws_secret_access_key:
        log.error("Failed to retrieve AWS credentials from Secret Manager.")
        return False

    try:
        ses_client = boto3.client(
            'ses',
            region_name=aws_region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key
        )
        
        subject = "Upcoming Rental Payments Due"

        # Create the root message and set the headers.
        msg = MIMEMultipart('mixed')
        msg['Subject'] = subject
        msg['From'] = sender_email
        msg['To'] = landlord_email

        # Create a 'related' part for the HTML and embedded image.
        msg_related = MIMEMultipart('related')
        msg.attach(msg_related)
        
        # Create an 'alternative' part for the plain text and HTML.
        msg_alternative = MIMEMultipart('alternative')
        msg_related.attach(msg_alternative)

        msg_alternative.attach(MIMEText(text_body, 'plain'))
        msg_alternative.attach(MIMEText(html_body, 'html'))
        
        # Attach the logo
        current_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.normpath(os.path.join(current_dir, '..', 'templates', 'assets', 'apple-touch-icon.png'))
        with open(logo_path, 'rb') as f:
            logo_data = f.read()
        logo = MIMEImage(logo_data, 'png')
        logo.add_header('Content-ID', '<logo>')
        msg_related.attach(logo)
        
        ses_client.send_raw_email(
            Source=sender_email,
            Destinations=[landlord_email],
            RawMessage={'Data': msg.as_string()}
        )
        
        log.info(f"Successfully sent landlord summary email to {landlord_email}")
        return True
    except Exception as e:
        log.error(f"An unexpected error occurred while sending landlord summary email: {e}")
        return False