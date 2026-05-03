from irisctl import __version__


def test_version():
    assert __version__ == "0.1.0"


def test_imports():
    """Smoke: every module imports cleanly."""
    import irisctl
    import irisctl.output  # noqa: F401

    assert irisctl.__version__
