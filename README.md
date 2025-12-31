# HomeHive Cloud Functions

This repository contains the backend Cloud Functions for the HomeHive platform, designed to handle scheduled tasks and notifications for property management.

## Overview

This project includes four main Cloud Functions:

1.  **`main` (Scheduled Function):** A scheduler-triggered function that runs periodically (e.g., daily). It queries the Firebase Realtime Database to find tenants whose rent is due within a configurable window (e.g., 7 days). For each due tenant, it enqueues a task in Google Cloud Tasks.
2.  **`send_notification_worker` (HTTP Function):** An HTTP-triggered function designed to be invoked by Cloud Tasks. It receives a tenant's information in the request payload and sends them a rent reminder email using AWS Simple Email Service (SES). Landlord emails are currently disabled.
3.  **`get_invoice` (HTTP Function):** An HTTP-triggered function that allows tenants to securely stream their invoice as a PDF directly from Google Cloud Storage.
4.  **`generate_receipt` (HTTP Function):** An HTTP-triggered function that generates a receipt PDF for a given payment, stores it in Google Cloud Storage, and returns a URL to retrieve it.
5.  **`get_receipt` (HTTP Function):** An HTTP-triggered function that allows tenants to securely stream their receipt as a PDF directly from Google Cloud Storage.

This architecture provides a robust, scalable, and decoupled system for handling notifications and document access.

## Repository Contents

*   `functions/main.py`: Contains the core Python code for the `main` scheduler function, the `send_notification_worker` function, and the `get_invoice`, `generate_receipt`, and `get_receipt` functions.
*   `functions/services/receipt_service.py`: Contains the logic for generating receipt PDFs.
*   `functions/requirements.txt`: Lists all the Python dependencies for the project (e.g., `firebase-functions`, `boto3`, `Jinja2`).
*   `functions/templates/reminder_email.html`: The Jinja2 template used to generate the body of the rent reminder email.
*   `functions/tests/`: Contains all the unit and integration tests.
    *   `test_main.py`: The main test file, containing tests for all functions and helpers.
    *   `test_receipt.py`: Contains tests for the receipt generation functionality.
    *   `test_db.json`: A snapshot of the database schema used for mock data in the tests.
*   `firebase.json` & `.firebaserc`: Configuration files for deploying with the Firebase CLI.
*   `README.md`: This file, providing an overview and instructions for the project.

## Recent Changes

*   **Invoice Reference:** The invoice reference is now stored in the `accounts` section of the database.
*   **Landlord Emails:** Landlord reminder emails have been disabled.
*   **Invoice Streaming:** A new `get_invoice` function has been added to allow tenants to securely stream their invoices as PDFs.
*   **Receipt Generation:** New `generate_receipt` and `get_receipt` functions have been added to generate and stream receipt PDFs.

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

### Testing Receipt Generation

To test the `generate_receipt` function, you can use `curl` to send a POST request to the function's URL. You will need to replace `YOUR_CLOUD_FUNCTION_URL` with the actual URL of your deployed function.

```bash
curl -X POST -H "Content-Type: application/json" \
-d '{
  "tenant_name": "John Doe",
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

The function will respond with a URL to the generated receipt PDF. You can then use this URL to download the receipt.

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