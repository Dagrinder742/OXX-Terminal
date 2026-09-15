echo -e "\033[35m°/^| Arch•i°techT | AI-GEMINI |^\°\033[0m"
echo -e "\033[35m°°°°°°°°°°°°°°°°°°°°°°°°°°°°°°°°°°\033[0m"
echo -e "\033[35m°{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}°\033[0m"

cd ~/OKX-Terminal

echo -e "\033[33m[+] RUNNING MAINTENANCE...\033[0m"
echo -e "\033[33m[+] RUNNING PACKAGE UPDATES...\033[0m"
pkg update && pkg upgrade

export PYTHONWARNINGS="ignore"

echo -e "\033[33m[+] RUNNING MAINTENANCE...\033[0m"
echo -e "\033[33m[+] RUNNING BANDIT.YAML...\033[0m"
bandit -c bandit.yaml -r . --severity-level all --confidence-level all --ignore-nosec

echo -e "\033[33m[+] RUNNING MAINTENANCE...\033[0m"
echo -e "\033[33m[+] Running Pip Audit...\033[0m"
pip-audit

export PATH="$HOME/.cargo/bin:$PATH"
