"""Sample repository fixture for integration tests."""

def greet(name: str) -> str:
    return f"Hello, {name}"


def main() -> None:
    print(greet("CodeOrbit"))


if __name__ == "__main__":
    main()
