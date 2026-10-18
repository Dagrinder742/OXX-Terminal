def calculate_profit_margin(cost, revenue):
    if cost == 0 or revenue == 0:
        raise ZeroDivisionError("Cost or revenue cannot be zero.")
    return (revenue - cost) / revenue
