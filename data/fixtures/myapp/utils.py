import os.path
import json


# Function with 4 params — target for ">3 params" analysis task
def parse_csv(filepath, delimiter=",", encoding="utf-8", skip_header=True):
    # TODO: add support for quoted fields
    results = []
    with open(filepath, encoding=encoding) as f:
        lines = f.readlines()
        if skip_header:
            lines = lines[1:]
        for line in lines:
            results.append(line.strip().split(delimiter))
    return results


def resolve_path(base, *parts):
    return os.path.join(base, *parts)


def format_json(data, indent=2):
    return json.dumps(data, indent=indent)


def validate_input(value, min_val, max_val):
    if not isinstance(value, (int, float)):
        raise TypeError(f"Expected number, got {type(value)}")
    if value < min_val or value > max_val:
        raise ValueError(f"{value} out of range [{min_val}, {max_val}]")
    return True
