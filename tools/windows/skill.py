import random

class Skill:
    def __init__(self):
        self.state = {"environment": {}, "actions": []}

    def perceive(self):
        # Mock environmental metrics
        self.state["environment"] = {
            "temperature": random.randint(10, 30),
            "humidity": random.randint(40, 80),
            "light": random.randint(0, 100)
        }
        print("Perceive: Environment =", self.state["environment"])

    def reason(self):
        # Generate 3 action choices based on environmental metrics
        actions = [
            f"Action 1: Increase temperature to {self.state['environment']['temperature'] + 5}",
            f"Action 2: Decrease humidity to {self.state['environment']['humidity'] - 10}",
            f"Action 3: Increase light to {self.state['environment']['light'] + 20}"
        ]
        self.state["actions"] = actions
        print("Reason: Actions =", self.state["actions"])

    def evaluate(self):
        # Score actions using a random metric
        scores = [(action, random.randint(1, 10)) for action in self.state["actions"]]
        scores.sort(key=lambda x: x[1], reverse=True)
        print("Evaluate: Scores =", scores)
        return scores[0][0]

    def act(self, chosen_action):
        # Print the chosen action
        print("Act: Chosen Action =", chosen_action)

    def think(self):
        # Call all four sequentially
        self.perceive()
        self.reason()
        scores = self.evaluate()
        chosen_action = self.evaluate()
        self.act(chosen_action)
        print("Think: Pipeline steps completed")

if __name__ == "__main__":
    skill = Skill()
    skill.think()
