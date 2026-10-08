# Module 2 Output: State Synchronization & Order Book (Llama-3.2-1B-Instruct)

## Prompt Executed
Building on an asynchronous websocket script, implement an in-memory local order book class that handles initial snapshot frames and incoming incremental delta updates (`l2update`). Properly sort bids in descending order and asks in ascending order by price. Implement strict sequence-gap detection and validation to discard out-of-order frames, stale sequence numbers, or duplicate payloads. Provide clean Python code blocks.

## Model Output
```python
class OrderBook:
    def __init__(self):
        self.order_book = self._initialize_order_book()

    def _initialize_order_book(self):
        order_book = []
        for frame in self.get_snapshot_frames():
            bids = sorted(frame['bids'], key=lambda x: x['price'], reverse=True)
            asks = sorted(frame['asks'], key=lambda x: x['price'], reverse=True)
            order_book.extend(bids)
            order_book.extend(asks)
        return order_book

    def get_snapshot_frames(self):
        return [
            {'bids': [
                {'price': 100.0, 'size': 100},
                {'price': 120.0, 'size': 50},
                {'price': 110.0, 'size': 200},
            ], 'asks': [
                {'price': 100.0, 'size': 100},
                {'price': 130.0, 'size': 50},
                {'price': 125.0, 'size': 200},
            ]},
            {'bids': [
                {'price': 105.0, 'size': 50},
                {'price': 115.0, 'size': 100},
                {'price': 115.0, 'size': 150},
            ], 'asks': [
                {'price': 105.0, 'size': 50},
                {'price': 125.0, 'size': 50},
                {'price': 105.0, 'size': 100},
            ]},
        ]

    def process_incremental_delta(self, l2_update):
        if not self.is_valid_delta_update(l2_update):
            raise ValueError("Invalid delta update")
        self.order_book = self._update_order_book(self.order_book, l2_update['bids'], l2_update['asks'], l2_update['sequence'])

    def is_valid_delta_update(self, l2_update):
        for i in range(len(l2_update['bids'])):
            if i > 0 and l2_update['bids'][i]['price'] != l2_update['bids'][i-1]['price']:
                return False
            if i > 0 and l2_update['bids'][i]['size'] != l2_update['bids'][i-1]['size']:
                return False
        return True

    def _update_order_book(self, order_book, bids, asks, sequence):
        bids = sorted(bids, key=lambda x: x['price'], reverse=True)
        asks = sorted(asks, key=lambda x: x['price'], reverse=True)
        new_order_book = []
        for bid in bids:
            new_order_book.append({'bids': [bid], 'asks': []})
        for ask in asks:
            new_order_book.append({'bids': [], 'asks': [ask]})
        for i in range(len(bids)):
            for j in range(i+1, len(bids)):
                if bids[i]['size'] > bids[j]['size']:
                    new_order_book[i]['bids'].append(bids[j])
                elif bids[i]['size'] < bids[j]['size']:
                    new_order_book[j]['asks'].append(bids[i])
        return new_order_book

    def get_order_book(self):
        return self.order_book
