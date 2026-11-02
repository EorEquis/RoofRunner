# These tests do not exercise the roof, nor do they validate your hardware/connections/roof setup.  They are automated tests of the *code only*, using *simulated hardware*.

You are responsible for physical end to end testing of your setup.

## Running the Tests

RoofRunner's automated tests use `pytest` and a simulated SMC. They do not communicate with the real motor controller or move the roof. The test suite can be run from an SSH terminal connected to the RoofRunner Pi, without affecting the running Docker container.

### Initial setup

- Check out the main branch
- Create a virtual environment **outside the repository** and activate it.  This allows the virtual environment and installed packages live in `~/.venvs/roofrunner-tests`, not in the main repository or Docker container:

```bash
mkdir -p ~/.venvs
python3 -m venv ~/.venvs/roofrunner-tests
source ~/.venvs/roofrunner-tests/bin/activate
```
- Install the testing dependencies:

```bash
pip install -r requirements-dev.txt
```

### Run the tests

From the RoofRunner repository directory, with the virtual environment active:

```bash
python -m pytest -v
```

Pytest reports each test's result and a summary. 

## Subsequent runs

The virtual environment only needs to be created and populated once. For future runs:

```bash
cd ~/RoofRunner
source ~/.venvs/roofrunner-tests/bin/activate
python -m pytest -v
```


