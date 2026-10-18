class OrderProcessor:
    def __init__(self):
        self.orders = []

    def add_order(self, price, tax, total_items):
        try:
            total_price = price + (price * tax / 100)
            self.orders.append({"price": total_price, "total_items": total_items})
            print(f"Added order: price = {total_price}, total_items = {total_items}")
        except TypeError:
            print("Error: Tax must be a number.")

    def process_orders(self):
        if not self.orders:
            print("No orders to process.")
            return
        for order in self.orders:
            print(f"Processing order: price = {order['price']}, total_items = {order['total_items']}")

if __name__ == "__main__":
    processor = OrderProcessor()
    processor.add_order(100, "string_tax", 5)
    processor.process_orders()
