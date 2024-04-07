# Data Economy Hackathon
IPFS Huggingface Bridge

Author - Benjamin Barber
QA - Kevin De Haan

# About

This is a model manager and wrapper for huggingface, looks up a index of models from an collection of models, and will download a model from either https/s3/ipfs, depending on which source is the fastest.

# How to use

setup.py

TODO

# To scrape huggingface

interactive prompt:

node scraper.js 

import a model:

node scraper.js hf "dataset" (as defined in your .json files)

import all models 

node scraper.js hf 