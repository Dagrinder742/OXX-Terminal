# =================================================================================================
# KALSHI DIRECTORY WORK FILES AND DOCUMENTATION
# =================================================================================================

* **auth.py** 
Description: 
Secure cryptographic utility module handling RSA private key loading, RSA-PSS signature generation, 
and production header creation with URL-stripping safeguards for Kalshi API requests.
* **test_connection.py**: Live authentication test script verifying production REST connectivity 
and balance retrieval.
* **models.py**: Pydantic data validation schemas for accounts, balances, and real-time market 
feeds.
* **howto.md**: Official Kalshi integration guide detailing RSA signature concatenation rules and 
query parameter stripping.
* **asyncapi.yaml**: Kalshi Market Data WebSocket API specification (v2.0.0), covering real-time 
channels, error codes, and command structures.
* **client.py**: Asynchronous WebSocket client establishing live authenticated connections to 
Kalshi's production stream with subscription management.
