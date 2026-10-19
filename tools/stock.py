class Stock:
    def __init__(self):
        self.state = {"items": {}, "log": []}

    def load(self):
        self.state["items"] = {"bolts": 40, "nuts": 5, "screws": 12}
        print("load: items =", self.state["items"])

    def rank(self):
        ranked = sorted(self.state["items"].items(), key=lambda kv: kv[1])
        print("rank: lowest first =", ranked)
        return ranked

    def pick(self, ranked):
        name, qty = ranked[0]
        print("pick: reorder", name, "(only", qty, "left)")
        return name

    def run(self):
        for _ in range(2):
            self.load()
            choice = self.pick(self.rank())
            self.state["log"].append(choice)


if __name__ == "__main__":
    Stock().run()
