# Import necessary libraries
import time

# Define the order book class
class OrderBook:
    def __init__(self):
        # Initialize the order book with empty lists for bids and asks
        self.bids = []
        self.asks = []

    def add_order(self, order_type, price, quantity):
        # Add an order to the appropriate list based on order type
        if order_type == 'bid':
            self.bids.append((price, quantity))
        elif order_type == 'ask':
            self.asks.append((price, quantity))
        else:
            print("Invalid order type")

    def sort_order_book(self):
        # Sort the bids in descending order and asks in ascending order
        self.bids.sort(key=lambda x: x[0], reverse=True)
        self.asks.sort(key=lambda x: x[0])

    def check_sequence_gap(self):
        # Check for any sequence gaps in the order book
        for i in range(len(self.bids) - 1):
            if self.bids[i + 1][0] - self.bids[i][0] < 0:
                print("Sequence gap detected")

        for i in range(len(self.asks) - 1):
            if self.asks[i + 1][0] - self.asks[i][0] > 0:
                print("Sequence gap detected")

# Function to run the order book engine for 50 iterations
def run_order_book_engine():
    book = OrderBook()

    for _ in range(50):
        book.add_order('bid', 1.0, 10)  # Add a bid order
        book.add_order('ask', 2.0, 20)  # Add an ask order
        book.sort_order_book()  # Sort the order book
        book.check_sequence_gap()  # Check for sequence gaps

        # Print current state of the order book
        print("Order Book State:")
        print("Bids:", book.bids)
        print("Asks:", book.asks)
        print()

        time.sleep(0.05)  # Wait for 0.05 seconds before next iteration

# Execute the order book engine
run_order_book_engine()