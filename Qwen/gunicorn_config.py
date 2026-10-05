bind = "0.0.0.0:5000"
workers = 4
threads = 10



### Step 3: Run Gunicorn

# You can run Gunicorn with the following command:

# ```bash
# gunicorn -c gunicorn_config.py app:app
