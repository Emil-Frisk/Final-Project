#!/bin/bash
echo "Installing virtual enviroment..."
python3 -m venv .venv
echo "venv installed!"

echo "Activating enviroment"
source .venv/bin/activate

echo "Installing all the requirements from requirements.txt"
pip install -r requirements.txt
echo "All dependencies downloaded!"
echo "Launch the API with command python3 ExcavatorAPI.py"