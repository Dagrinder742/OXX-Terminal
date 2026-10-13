# Importing necessary libraries
import asyncio
import time

# Creating a lock object
lock = asyncio.Lock()

# Function to simulate data ingestion
async def data_ingestion():
    for i in range(50):  # 50 iterations
        print(f"Data ingestion: {i}")
        await asyncio.sleep(0.05)  # Simulating a delay
        async with lock:
            # Simulating telemetry logging
            print("Telemetry logging: " + str(i))

# Function to simulate background telemetry logging
async def background_logging():
    for i in range(50):  # 50 iterations
        print(f"Background logging: {i}")
        await asyncio.sleep(0.05)  # Simulating a delay

# Main function to tie the resilient gateway and order book together
async def main():
    # Starting the data ingestion task
    await data_ingestion()
    
    # Starting the background logging task
    await background_logging()

# Running the main function
asyncio.run(main())