# Cloud Function Project

This project contains a Python Cloud Function managed with Firebase.

## Prerequisites

- **pyenv**: This project uses `pyenv` to manage Python versions. Please ensure you have `pyenv` installed.
- **Python Version**: This project requires Python 3.12.0. You can install it with `pyenv`:
  ```bash
  pyenv install 3.12.0
  ```
- **Firebase CLI**: You will need the Firebase CLI to deploy the function.

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

## Running Tests

To run the tests, make sure you are in the project root directory.

**Run all tests:**
```bash
source functions/venv/bin/activate && python -m unittest discover functions/tests
```

**Run a specific test file:**
```bash
source functions/venv/bin/activate && python -m unittest functions.tests.test_main
```

**Run a specific test class:**
```bash
source functions/venv/bin/activate && python -m unittest functions.tests.test_main.TestMain
```

**Run a specific test method:**
```bash
source functions/venv/bin/activate && python -m unittest functions.tests.test_main.TestMain.test_notification_handler
```

## Test Coverage

This project uses the `coverage` library to measure test coverage.

1.  **Run Tests with Coverage:**
    From the project root, run:
    ```bash
    source functions/venv/bin/activate && coverage run -m unittest discover functions/tests
    ```

2.  **View Console Report:**
    For a quick summary in your terminal:
    ```bash
    coverage report
    ```

3.  **View HTML Report:**
    For a detailed, interactive report that shows which lines were missed:
    ```bash
    coverage html
    ```
    This will create an `htmlcov/` directory. Open the `index.html` file inside it to view the report.

## Deployment

To deploy the function, run the following command from the project root directory:

```bash
firebase deploy --only functions
```
