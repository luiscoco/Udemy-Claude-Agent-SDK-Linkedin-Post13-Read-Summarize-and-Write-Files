"""The small application described by this project's README."""
import argparse


def main():
    parser = argparse.ArgumentParser(description="Print a friendly greeting.")
    parser.add_argument("name", nargs="?", default="World")
    args = parser.parse_args()
    print(f"Hello, {args.name}! Welcome to the demo project.")


if __name__ == "__main__":
    main()
