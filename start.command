#!/bin/zsh
cd -- "$(dirname -- "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Run these setup commands in this folder first:"
  echo "python3 -m venv .venv"
  echo ".venv/bin/python -m pip install -r requirements.txt"
  echo ".venv/bin/python download_model.py"
  read -r "reply?Press Enter to close."
  exit 1
fi
.venv/bin/python app.py
