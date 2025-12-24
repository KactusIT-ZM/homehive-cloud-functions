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

def send_reminder_email(tenant_info: dict, template_env, invoice_pdf: bytes = None) -> bool:
    """
    Sends a rent reminder email to the tenant.
    Returns True if successful, False otherwise.
    """
    recipient_email = tenant_info.get('email')
    due_date = tenant_info.get('dueDate')
    tenant_name = tenant_info.get('name', 'Tenant')

    if not recipient_email:
        log.error(f"No email for tenant {tenant_info.get('tenant_id')}. Skipping email.")
        return False
        
    aws_region = "us-east-1" # Hardcoding for security and consistency with Secret Manager credentials
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

    # Render the email body from the template
    template = template_env.get_template('reminder_email.html')
    html_body = template.render(
        name=tenant_name, 
        dueDate=due_date,
        property_name=tenant_info.get('property_name', 'N/A'),
        rent_amount=tenant_info.get('rent_amount', 'N/A')
    )
    # Create a plain text version as a fallback
    text_body = f"Hi {tenant_name},\n\nThis is a friendly reminder that your rent payment for {tenant_info.get('property_name', 'N/A')} amounting to ZMW {tenant_info.get('rent_amount', 'N/A')} is due soon.\nYour upcoming rent payment is due on: {due_date}.\n\nPlease log in to your HomeHive portal to view your statement or make a payment: https://your-homehive-portal.com\n\nIf you have already made this payment or have any questions, please disregard this email or contact us directly.\n\nThank you for being a valued tenant.\n\nSincerely,\nThe HomeHive Team\n\n© 2025 HomeHive. All rights reserved.\nThis is an automated message, please do not reply."
    
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
        
        subject = "Reminder: Upcoming Rent Payment Due"

        # Create the root message and set the headers.
        msg = MIMEMultipart('mixed')
        msg['Subject'] = subject
        msg['From'] = sender_email
        msg['To'] = recipient_email

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

        # Attach PDF if it exists
        if invoice_pdf:
            part = MIMEApplication(invoice_pdf, Name='invoice.pdf')
            part['Content-Disposition'] = 'attachment; filename="invoice.pdf"'
            msg.attach(part)
        
        ses_client.send_raw_email(
            Source=sender_email,
            Destinations=[recipient_email],
            RawMessage={'Data': msg.as_string()}
        )
        
        log.info(f"Successfully sent email reminder to {recipient_email}")
        return True
    except Exception as e:
        log.error(f"An unexpected error occurred while sending email: {e}")
        return False
