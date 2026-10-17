class Portfolio:
    def __init__(self):
        self.positions = []

    def add_trade(self, trade):
        self.positions.append(trade)

    def calculate_total_value(self):
        total_value = 0
        for trade in self.positions:
            total_value += int(trade['qty']) * float(trade['price'])  # Fixed: convert qty to int and price to float
        return total_value

    def print_summary(self):
        total_value = self.calculate_total_value()
        print(f"Total Portfolio Value: ${total_value:.2f}")

if __name__ == "__main__":
    portfolio = Portfolio()
    portfolio.add_trade({'symbol': 'AAPL', 'qty': 100, 'price': '150.00'})
    portfolio.add_trade({'symbol': 'GOOGL', 'qty': 50, 'price': '2500.00'})
    portfolio.print_summary()
