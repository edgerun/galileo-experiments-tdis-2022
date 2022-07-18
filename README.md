# Galileo experiments TDIS 2022
This repository contains code that was used to evaluate our submission for the Workshop on Testing Distributed Internet of Things Systems 2022.

Install
=======
The project supports Python3.9+.

Run:

    python3.9 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

Afterwards you can run the `main.py` scripts, as well as Jupyter notebook (`jupyter notebook`).

Run
===

The project serves in total three purposes:

1. Run a profiling experiment, whereas a Mobilenet OpenFaaS-based function is deployed (see `evaluation.profiling.mobilenet.main`)
2. Run a scenario experiment (`evaluation.scenario.main`) as well as a program that randomly schedules and tears down applications (`evaluation.scenario.randomscheduler.main`)
3. Analyse the aforementioned experiments using Jupyter Notebooks (see `notebooks/`)