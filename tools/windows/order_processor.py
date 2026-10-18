class OrderProcessor:
    def __init__(self):
        self.orders = []

    def add_order(self, price, tax, total_items):
        self.orders.append({"price": price, "tax": tax, "total_items": total_items})

    def calculate_total(self):
        total = 0
        for order in self.orders:
            total += order["price"] + float(order["price"]) * order["tax"]
        return total

    def process_orders(self):
        if self.orders:
    total = self.calculate_total()
else:
    print("No orders to process.")
        print(f"Total: ${total:.2f}")

if __name__ == "__main__":
    processor = OrderProcessor()
    processor.add_order(100, 0.05, 10)
    processor.process_orders()
