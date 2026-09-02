"""Test package.

It exists so `tests/mongo_support.py` can be imported the same way whichever command runs the
suite: `python -m unittest discover -s tests` puts this directory on `sys.path`, while
`python -m unittest tests.test_app` does not, and a helper that only resolved under one of them
is a helper nobody can use to run a single module.
"""
