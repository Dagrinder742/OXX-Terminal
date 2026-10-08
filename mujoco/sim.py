import mujoco
import numpy as np

# Load a standard physics model (XML-based description)
model = mujoco.MjModel.from_xml_path("path_to_model.xml")
data = mujoco.MjData(model)

# The simulation execution loop (just like your automated scripts)
while data.time < 10.0:
    mujoco.mj_step(model, data)
    # Here is where you read telemetry, check variables, or log state errors
    print(f"Time: {data.time}, Position: {data.qpos}")

