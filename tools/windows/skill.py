class Skill:
    def __init__(self):
        self.state = {"metrics": {}, "history": []}

    def perceive(self):
        import random
        self.state["metrics"] = {
            "temperature": random.randint(10, 30),
            "humidity": random.randint(40, 80),
            "light": random.randint(0, 100)
        }
        print("Perceive:", self.state["metrics"])
        return self.state["metrics"]

    def reason(self):
        actions = ["move", "rest", "work"]
        print("Reason:", actions)
        return actions

    def evaluate(self, actions):
        scores = {action: len(action) for action in actions}
        max_score = max(scores.values())
        best_action = [action for action, score in scores.items() if score == max_score][0]
        print("Evaluate:", scores)
        return best_action

    def act(self, action):
        print("Act:", action)
        return action

    def think(self, rounds=3):
        for _ in range(rounds):
            metrics = self.perceive()
            actions = self.reason()
            best_action = self.evaluate(actions)
            self.act(best_action)
            self.state["history"].append(best_action)
        return self.state["history"]

if __name__ == "__main__":
    Skill().think()
