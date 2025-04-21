def print_pyramid(height):
    for i in range(height):
        # Пробелы перед звездочками
        spaces = " " * (height - i - 1)
        # Звездочки
        stars = "*" * (2 * i + 1)
        print(spaces + stars)

def print_diamond():
    print("   *   ")
    print("  ***  ")
    print(" ***** ")
    print("*******")
    print(" ***** ")
    print("  ***  ")
    print("   *   ")

if __name__ == "__main__":
    print("Демонстрация фигур:\n")
    print("1. Пирамида:")
    print_pyramid(5)
    print("\n2. Ромб:")
    print_diamond()