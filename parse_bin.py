import re
import sys

def extract_strings(file_path, min_length=4):
    with open(file_path, 'rb') as f:
        content = f.read()

    # Regex to find continuous printable ASCII characters of a minimum length
    pattern = b'[ -~]{%d,}' % min_length
    strings = re.findall(pattern, content)

    return [s.decode('ascii', errors='ignore') for s in strings]

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 parse_bin.py <binary_file>")
        sys.exit(1)

    filename = sys.argv[1]
    print(f"Extracting strings from {filename}...\n")

    try:
        found_strings = extract_strings(filename)
        for s in found_strings:
            print(s)
    except Exception as e:
        print(f"Error reading file: {e}")

