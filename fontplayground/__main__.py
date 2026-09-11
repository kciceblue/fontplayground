"""Entry point: `python -m fontplayground` or the `fontplayground` console script."""


def main() -> None:
    from fontplayground.ui.app import main as run

    run()


if __name__ == "__main__":
    main()
