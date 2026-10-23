# Security

`sandbox-tool` is a guard against a model's mistakes and tricks. It is **not** a container and
not a boundary against a determined attacker (see "What it does not protect against" in the README).

If you find a way for an agent to read, write, delete or run something outside the sandbox folder,
please report it privately using GitHub's **"Report a vulnerability"** button on the repository's
Security tab (the maintainer must enable private vulnerability reporting under Settings -> Code
security). Include the command or script, what you expected, and what happened.
Please do not open a public issue for a working escape until it is fixed.
