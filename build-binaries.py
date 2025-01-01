import os
import subprocess
import platform

# Define configurations for each platform
targets = [
    {"name": "Windows", "image": "cdrx/pyinstaller-windows", "extension": ".exe"},
    {"name": "Linux", "image": "cdrx/pyinstaller-linux", "extension": ""},
    {"name": "MacOS", "image": "cdrx/pyinstaller-macos", "extension": ""}
]

script_name = "main.py"
output_dir = "bin"

# Create the output directory
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

def build_binary(target):
    print(f"Building for {target['name']}...")
    try:
        # Run Docker container for the specified platform
        subprocess.run([
            "docker", "run", "--rm",
            "-v", os.getcwd() + ":/src",
            target["image"],
            "--onefile",
            f"/src/{script_name}"
        ], check=True)

        # Move the binary to the output directory
        binary_name = os.path.splitext(script_name)[0] + target["extension"]
        src_binary = os.path.join("dist", binary_name)
        dest_binary = os.path.join(output_dir, f"{binary_name}_{target['name'].lower()}")
        os.rename(src_binary, dest_binary)
        print(f"Built {dest_binary}")
    except subprocess.CalledProcessError as e:
        print(f"Error building for {target['name']}: {e}")

def main():
    current_os = platform.system()
    if current_os not in ["Linux", "Darwin"]:  # Docker is best run on Linux/Mac
        print("This script requires Docker and is best run on Linux or macOS.")
        return

    # Ensure Docker is installed
    try:
        subprocess.run(["docker", "--version"], check=True, stdout=subprocess.PIPE)
    except FileNotFoundError:
        print("Docker is not installed. Please install Docker and try again.")
        return

    for target in targets:
        build_binary(target)

    print(f"All binaries are saved in the '{output_dir}' directory.")

if __name__ == "__main__":
    main()