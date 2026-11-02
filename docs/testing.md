# Running the Tests

RoofRunner's automated tests use `pytest` and a simulated SMC. They do not communicate with the real motor controller or move the roof. The test suite can be run from a VS Code Remote SSH terminal connected to the RoofRunner Pi, without affecting the running Docker container.

## Initial setup

Check out the branch containing the tests (or `main` after the test harness is merged):

```bash
cd ~/RoofRunner
git switch test-harness
git pull
```

Create a virtual environment **outside the repository** and activate it:

```bash
mkdir -p ~/.venvs
python3 -m venv ~/.venvs/roofrunner-tests
source ~/.venvs/roofrunner-tests/bin/activate
```

Install the testing dependencies:

```bash
pip install -r requirements-dev.txt
```

## Run the tests

From the RoofRunner repository directory, with the virtual environment active:

```bash
python -m pytest -v
```

Pytest reports each test's result and a summary. The initial test run completed with **20 passed**.

## Subsequent runs

The virtual environment only needs to be created and populated once. For future runs:

```bash
cd ~/RoofRunner
source ~/.venvs/roofrunner-tests/bin/activate
python -m pytest -v
```

The virtual environment and installed packages live in `~/.venvs/roofrunner-tests`, not in the repository. Pytest may create `.pytest_cache/` and `__pycache__/` directories; these are temporary artifacts and should not be committed.
