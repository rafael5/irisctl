"""Allow `python -m irisctl …` invocation."""

from irisctl.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
