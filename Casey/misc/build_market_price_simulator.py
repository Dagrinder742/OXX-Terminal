import random
import time

def generate_prices(num_prices):
    prices = []
    for i in range(num_prices):
        price = random.uniform(1000, 50000)  # generate a random price between 1000 and 50000
        prices.append(price)
        if i == num_prices - 1:  # if this is the last price, print it as a high extreme
            print(f"High extreme: {price}")
        elif price > max(prices):  # if this price is higher than the max, print it as a high extreme
            print(f"High extreme: {price}")
        elif price < min(prices):  # if this price is lower than the min, print it as a low extreme
            print(f"Low extreme: {price}")
        time.sleep(0.05)  # sleep for 0.05 seconds to avoid infinite loop

if __name__ == "__main__":
    generate_prices(50)