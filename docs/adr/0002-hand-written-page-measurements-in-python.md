# Hand-written web page; measurements declared in Python

The UI is a small hand-written HTML/JS page (no npm, no build step) with uPlot for plots, served by FastAPI. Each measurement is a Python class that declares its parameters and traces, and the page builds its forms and plots from those declarations, so adding a measurement never requires web code. We chose this over NiceGUI (Python-only UI) because it gives full control of the instrument look and fast enough plotting for multi-channel MKID streams, while lab members still only write Python.
