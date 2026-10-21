import random

class Skill:
    def __init__(self):
        self.state = {
            "metrics": {},
            "history": [],
            "energy": 100,
            "cycles": 0
        }

    def perceive(self):
        metrics = {
            "temperature": random.randint(10, 30),
            "humidity": random.randint(40, 80),
            "light": random.randint(0, 100)
        }
        print("Perceive:", metrics)
        self.state["metrics"] = metrics
        return metrics

    def reason(self, metrics):
        actions = ["scout", "patrol", "rest"]
        if metrics["temperature"] > 25:
            actions[0] = "cool_down"
        if metrics["light"] < 20:
            actions[1] = "illuminate"
        print("Reason:", actions)
        return actions

    def evaluate(self, actions):
        scores = {action: len(action) for action in actions}
        highest_score = max(scores.values())
        highest_action = [action for action, score in scores.items() if score == highest_score][0]
        print("Evaluate:", scores)
        return highest_action

    def act(self, action):
        self.state["energy"] = max(0, self.state["energy"] - 15)
        self.state["cycles"] += 1
        print("Act:", action, "remaining energy:", self.state["energy"])
        return action

    def think(self, rounds=3):
        for _ in range(rounds):
            metrics = self.perceive()
            actions = self.reason(metrics)
            action = self.evaluate(actions)
            self.act(action)
            self.state["history"].append(action)
            if self.state["energy"] == 0:
                break
        return self.state["history"]

    def report(self):
        report = {
            "total_cycles": self.state["cycles"],
            "remaining_energy": self.state["energy"],
            "actions_taken": len(self.state["history"])
        }
        print("Report:", report)
        return report

if __name__ == "__main__":
    s = Skill()
    s.think()
    s.report()
