

class Equity:
    def __init__(self, symbol, initial_balance=0):
        self.symbol = symbol
        self.balance = initial_balance
        self.position = 0  # Number of shares held
        self.trade_history = []  # List to record trade history

    def buy(self, price, quantity):
        cost = price * quantity
        if cost <= self.balance:
            self.balance -= cost
            self.position += quantity
            self.trade_history.append(('buy', price, quantity))
            return True
        else:
            print("Insufficient balance to buy")
            return False

    def sell(self, price, quantity):
        if quantity <= self.position:
            revenue = price * quantity
            self.balance += revenue
            self.position -= quantity
            self.trade_history.append(('sell', price, quantity))
            return True
        else:
            print("Insufficient position to sell")
            return False

    def get_balance(self):
        return self.balance

    def get_position(self):
        return self.position

    def get_trade_history(self):
        return self.trade_history