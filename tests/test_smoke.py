import butler


def test_package_imports() -> None:
    assert butler.__name__ == "butler"
