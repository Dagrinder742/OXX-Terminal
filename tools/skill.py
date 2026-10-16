import random

class Skill:
    def __init__(self):
        self.state = {"environment": {}, "actions": []}

    def perceive(self):
        # Mock environmental metrics
        self.state["environment"] = {
            "temperature": random.uniform(20, 30),
            "humidity": random.uniform(40, 60),
            "pressure": random.uniform(1013, 1015)
        }
        print("Perceive: Environment =", self.state["environment"])

    def reason(self):
        # Generate 3 action choices based on environmental metrics
        actions = [
            f"Adjust Temperature to {self.state['environment']['temperature'] + 1}",
            f"Adjust Humidity to {self.state['environment']['humidity'] - 5}",
            f"Check Pressure at {self.state['environment']['pressure'] + 0.1}"
        ]
        self.state["actions"] = actions
        print("Reason: Actions =", self.state["actions"])

    def evaluate(self):
        # Score actions using a random metric
        scores = [(action, random.randint(1, 10)) for action in self.state["actions"]]
        scores.sort(key=lambda x: x[1], reverse=True)
        print("Evaluate: Scores =", scores)
        return scores[0][0]

    def act(self, action):
        # Print the chosen action
        print("Act: Chosen Action =", action)

    def think(self):
        # Call all four methods in a loop
        for _ in range(3):
            self.perceive()
            self.reason()
            score, action = self.evaluate()
            self.act(action)
            print("Think: Pipeline Step Complete")

if __name__ == "__main__":
    skill = Skill()
    skill.think()
