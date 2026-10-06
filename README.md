# Network Planner

A simple, non-technical network planner. Just enter how many subnets you need and the number of devices in each.

## How to run
1. Open your terminal or command prompt.
2. Install the requirements by typing:
   ```bash
   pip install -r requirements.txt
   ```
3. Start the app by typing:
   ```bash
   streamlit run app.py
   ```
   (If that doesn't work, try `python -m streamlit run app.py`)

## What the output means
Once you generate your network, you will see a clean table. 
- **Network**: The starting address for your subnet.
- **CIDR & Subnet Mask**: Different ways to write the size of your subnet.
- **Usable IP range**: The addresses you can actually assign to your devices (computers, printers, etc).
- **Gateway**: The address usually given to your router.

You can download the results as an Excel or CSV file.
