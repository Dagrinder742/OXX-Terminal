>>> """ i need a custom ai tool that can plug into python and monitor okx BTC-USDT spot pair, i nee
... d it to analyze 1H candles, MACD, RSI, EMA20-200.
... """
Creating an AI-powered trading bot requires careful planning. You will have several
components involved in this setup:

1. **Price Data Retrieval:** Use the OKEx API (or another exchange's) for real-time price
data of BTC/USD spot pairs.

2. **Technical Indicators Calculation** using libraries like `ta-lib` or custom
implementations if preferred.

3. **Data Analysis and Trading Logic Implementation**, usually done with Python, along with
machine learning models to predict market movements based on the analyzed indicators (MACD,
RSI).

4. **Integration between your AI model outputs/predictions for trading decisions**.

5. **Monitoring System:** Custom tool that continuously analyzes incoming data in real-time
using 1-hour candles and other technical analysis metrics provided by libraries like
`ta-lib`.

6. **Custom Monitoring Tool Interface with Python**: This could be built as a web
application or through custom scripts running on your local machine to provide insights
based on the processed signals.

Here’s an outline of what you need in terms of coding:

1. Setup and installation:
    ```sh
    pip install ta-lib requests pandas numpy matplotlib sklearn azure-ai-ml okex-python-bin
# Example packages.
    ```

2. Data Retrieval using OKEx API (Example with Python):
    ```python
    import requests

    def get_price_data(symbol, time_frame="1h"):
        url = f"https://www.okex.com/api/v2/instruments/{symbol}/candles"

        params = {
            "time-frame": time_frame,
            # Add other necessary parameters according to API documentation.
        }

        headers = {"Content-Type": "application/json",
                   'X-OkExKey': '<YOUR_API_KEY>'}

        response = requests.get(url, params=params, headers=headers)
        return response.json()
    ```

3. Technical Indicators (MACD and RSI):
   ```python
   from ta import momentum

   def calculate_macd(data_series):
       macd_fast_expiry=12  # fast EMA period.
       macd_slow_expiry =26  # slow EMA period.

       data, _ = momentum.get_momentum(data=data_series['close'],
                                       short=numpy.array([macd_fast_expiry]),
long=numpy.array([macd_slow_expiry]))

       return {
           'MACD': (data['fast'] - data['slow']),
           'Signal_Line': None  # Add signal line calculation if needed.
       }

   def calculate_rsi(data_series, period=14):
       rsi = momentum.RSIIndicator(
                   close=data_series['close'],
                   window=period).sma

       return {
           'RSI': rsi,
            }
    ```

4. Data Analysis and Integration:
  ```python
import pandas as pd

def analyze_data(symbol, time_frame):
   data = get_price_data(symbol)

   df = pd.DataFrame(data) # Assuming it's structured correctly.

   macd_result = calculate_macd(df['close'])
   rsi_result = calculate_rsi(df['close'])

   return {
       'MACD': macd_result,
       'RSI': rsi_result
    }
  ```

5. Integration:
```python
from azure.ai.ml import Workspace

def predict_trend(symbol, time_frame):
   data_analysis_results=analyze_data(symbol,time_frame)

 # Add logic to make predictions based on the above results.
# For instance using a simple moving average crossover or machine learning model prediction.

```
6. Building Monitoring Tool with Python:
- This can be done via creating web-based applications (Flask/Django) which continuously
fetch, analyze and display real-time trading insights from various technical indicators you
set up previously for your BTC/USD spot pair.

7. **Note:** Ensure compliance to OKEx’s Terms of Service while fetching data.

This outline should give a good start on building the required monitoring tool with AI
integration into Python. You may need further customizations based upon specific
requirements, API changes or new insights derived from additional market analysis and
machine learning model training/validation.
