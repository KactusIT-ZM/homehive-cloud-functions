# HomeHive Cloud Functions

This repository contains the backend Cloud Functions for the HomeHive platform, designed to handle scheduled tasks and notifications for property management.

## Overview

This project includes seven main Cloud Functions:

1.  **`main` (Scheduled Function):** A scheduler-triggered function that runs periodically (e.g., daily). It queries the Firebase Realtime Database to find tenants whose rent is due within a configurable window (e.g., 7 days). For each due tenant, it enqueues a task to `send_notification_worker` in Google Cloud Tasks.
2.  **`send_notification_worker` (HTTP Function):** An HTTP-triggered function designed to be invoked by Cloud Tasks. It receives a tenant's information in the request payload and sends them a rent reminder email using AWS Simple Email Service (SES). Landlord emails are currently disabled.
3.  **`get_invoice` (HTTP Function):** An HTTP-triggered function that allows tenants to securely stream their invoice as a PDF directly from Google Cloud Storage.
4.  **`generate_receipt` (HTTP Function):** An HTTP-triggered function that generates a receipt PDF for a given payment, stores it in Google Cloud Storage, returns a URL to retrieve the PDF, and **asynchronously enqueues a task to `send_email_worker` to send a receipt email.**
5.  **`get_receipt` (HTTP Function):** An HTTP-triggered function that retrieves a receipt PDF from Google Cloud Storage based on URL parameters and streams its content directly to the client. **It does NOT trigger any email sending or other background processes.**
6.  **`get_document` (HTTP Function):** An HTTP-triggered function that retrieves a document from Firebase Storage and streams it to the client. It takes `companyId` and `documentId` as query parameters, fetches document metadata from Realtime Database, and securely streams the file. This hides the actual storage path from users.
7.  **`send_email_worker` (HTTP Function):** A generic HTTP-triggered function invoked by Cloud Tasks to send various types of emails (e.g., receipts, document shares) using a template-based system.

This architecture provides a robust, scalable, and decoupled system for handling notifications and document access.

## Repository Contents

*   `functions/main.py`: Contains the core Python code for all Cloud Functions.
*   `functions/services/receipt_service.py`: Contains the logic for generating receipt PDFs.
*   `functions/services/email_service.py`: Contains the logic for sending emails.
*   `functions/requirements.txt`: Lists all the Python dependencies for the project.
*   `functions/templates/`: Contains the Jinja2 templates for emails.
    *   `reminder_email.html`: Template for rent reminder emails (green theme).
    *   `receipt_email.html`: Template for receipt emails (green theme).
    *   `document_share_email.html`: Template for document sharing emails (green theme).
*   `functions/tests/`: Contains all the unit and integration tests.
    *   `test_main.py`: The main test file, containing tests for the main scheduler function.
    *   `test_receipt.py`: Contains tests for the receipt generation functionality.
    *   `test_email.py`: Contains tests for the email sending functionality.
    *   `test_db.json`: A snapshot of the database schema used for mock data in the tests.
*   `firebase.json` & `.firebaserc`: Configuration files for deploying with the Firebase CLI.
*   `README.md`: This file, providing an overview and instructions for the project.

## Recent Changes

*   **Invoice Reference:** The invoice reference is now stored in the `accounts` section of the database.
*   **Landlord Emails:** Landlord reminder emails have been disabled.
*   **Invoice Streaming:** A new `get_invoice` function has been added to allow tenants to securely stream their invoices as PDFs.
*   **Receipt Generation:** New `generate_receipt` and `get_receipt` functions have been added to generate and stream receipt PDFs.
*   **Generic Email Service:** A new `send_email_worker` function and a generic `send_email` service have been added to handle sending different types of emails.
*   **Document Sharing:** A new `get_document` function has been added to securely stream documents from Firebase Storage, hiding the actual storage path. The `send_email_worker` now supports document sharing emails using the `document_share_email.html` template.
*   **Email Template Consistency:** All email templates (reminder, receipt, document share) now use a consistent green theme (#4CAF50) for unified branding.

## Prerequisites

- **pyenv**: This project uses `pyenv` to manage Python versions. Please ensure you have `pyenv` installed.
- **Python Version**: This project requires Python 3.12.0. You can install it with `pyenv`:
  ```bash
  pyenv install 3.12.0
  ```
- **Firebase CLI**: You will need the Firebase CLI to deploy the function.
- **Google Cloud SDK (`gcloud`)**: Required for authentication and creating Cloud Tasks queues.

## Setup

1. **Set Local Python Version**

   Navigate to the project root directory and set the local Python version:
   ```bash
   pyenv local 3.12.0
   ```

2. **Create Virtual Environment**

   Navigate to the `functions` directory and create a virtual environment:
   ```bash
   cd functions
   python -m venv venv
   ```

3. **Install Dependencies**

   Activate the virtual environment and install the required packages:
   ```bash
   source venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Set Up Application Default Credentials (ADC)**

   To run tests that interact with Google Cloud services locally, you need to authenticate:
   ```bash
   gcloud auth application-default login
   ```

## Running Tests

To run the tests, make sure you are in the project root directory.

### Run a Specific Test

To run a single specific test method, use the following format:

```bash
functions/venv/bin/python -m unittest functions.tests.test_main.TestNotificationWorker.test_send_email_testing_mode_redirects_email
```

```bash
functions/venv/bin/python -m unittest functions.tests.test_main.TestEndtoEnd.test_main
```

**Run all tests:**
```bash
source functions/venv/bin/activate && python -m unittest discover functions/tests
```

## Testing New Features

### Understanding Receipt & Email Flow

It's important to understand the decoupled and asynchronous nature of the `generate_receipt` and email sending process:

1.  When you call the `generate_receipt` function, it does two main things:
    *   Generates and saves the PDF receipt to Cloud Storage.
    *   **Immediately enqueues a separate task to send the email.** This task targets the `send_email_worker` function.
2.  The `generate_receipt` function then returns the `get_receipt` URL to you. It does **not** wait for the email to be sent.
3.  The `send_email_worker` function is triggered independently by Google Cloud Tasks to process the email sending.
4.  The `get_receipt` function simply retrieves the PDF when its URL is accessed; it does not trigger any email sending.

This asynchronous design ensures responsiveness and resilience.

### Testing Receipt Generation and Emailing

To test the `generate_receipt` function, you can use `curl` to send a POST request to the function's URL. You will need to replace `YOUR_CLOUD_FUNCTION_URL` with the actual URL of your deployed function.

```bash
curl -X POST -H "Content-Type: application/json" \
-d '{
  "tenant_name": "John Doe",
  "tenant_email": "john.doe@example.com",
  "property_name": "The Grand Estate",
  "date_paid": "2025-12-31",
  "next_payment_date": "2026-01-31",
  "amount_paid": 1500.00,
  "additional_info": [
    {"title": "Rent", "amount": 1400.00},
    {"title": "Late Fee", "amount": 100.00}
  ],
  "id_number": "12345"
}' \
https://us-central1-homehive-8c7d4.cloudfunctions.net/generate_receipt
```

The function will respond with a URL to the generated receipt PDF. You can then use this URL to download the receipt. This will also enqueue a task to send the receipt to the specified `tenant_email`.

### Testing Document Sharing

To test the document sharing functionality:

1. **Upload a document** through the HomeHive management interface (Documents page)
2. **Send document to tenant** by selecting a tenant from the dropdown and clicking "Send Document"
3. The system will:
   - Call `send_email_worker` with the `document_share_email.html` template
   - Generate a secure Cloud Function URL (not direct storage URL)
   - Send an email to the tenant with a link to view the document

**Example Document URL format:**
```
https://us-central1-{project-id}.cloudfunctions.net/get_document?companyId={companyId}&documentId={documentId}
```

**Testing `get_document` directly:**
```bash
curl "https://us-central1-homehive-dev-89916.cloudfunctions.net/get_document?companyId=YOUR_COMPANY_ID&documentId=YOUR_DOCUMENT_ID"
```

The function will:
- Fetch document metadata from Realtime Database at `HomeHive/PropertyManagement/Documents/{companyId}/{documentId}`
- Parse the Firebase Storage URL from the document metadata
- Stream the file content directly to the client
- Set appropriate content-type headers (PDF, Word, Excel, images, etc.)

**Security Benefits:**
- Hides actual storage paths from users
- Centralized access control through Cloud Function
- Can add authentication/authorization checks in the future
- All document access is logged in Cloud Functions

## Test Coverage

This project uses the `coverage` library to measure test coverage.

1.  **Run Tests with Coverage:**
    From the project root, run:
    ```bash
    source functions/venv/bin/activate && coverage run --source=functions -m unittest discover functions/tests
    ```

2.  **View Console Report:**
    For a quick summary in your terminal:
    ```bash
    coverage report
    ```

3.  **View HTML Report:**
    For a detailed, interactive report:
    ```bash
    coverage html
    ```
    This will create an `htmlcov/` directory. Open the `index.html` file inside it to view the report.

## Deployment

To deploy the functions, run the following command from the project root directory:

```bash
firebase deploy --only functions
```

### Environment Variables

You will need to set the required environment variables in the Google Cloud console for the `send_notification_worker` function.

*   `SENDER_EMAIL`: The "From" address for your emails (e.g., `noreply@yourdomain.com`). This email must be a verified identity in AWS SES.
*   `AWS_REGION`: The AWS region your SES service is in (e.g., `us-east-1`).
*   `AWS_ACCESS_KEY_ID`: Your AWS access key.
*   `AWS_SECRET_ACCESS_KEY`: Your AWS secret key.

#### Andon Cord (Safety Net) for Testing

To prevent sending emails to real users during testing, you can set the `TESTING_MODE` environment variable.

*   **`TESTING_MODE`**: Set this to `true` to force all emails to be redirected to `info@kactusit.com`. If this variable is not set or is set to any other value, emails will be sent to the actual tenant's email address.