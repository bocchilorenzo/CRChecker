from os import path, makedirs, remove, listdir, _exit
import sys, time, argparse, urllib.request, zipfile
from mutagen.flac import FLAC
from subprocess import run
from tqdm import tqdm
from zlib import crc32
import chardet

file_path = path.dirname(__file__)


def main(args):
    flac_command = ""

    # Check if the FLAC decoder is installed
    # On Windows, download the executable to avoid PATH issues
    if sys.platform == "win32" or sys.platform == "cygwin":
        if not path.exists(path.join(file_path, "utils", "flac-1.4.3-win")):
            download_flac()

        if sys.maxsize > 2 ** 32:
            flac_command = path.join(
                file_path, "utils", "flac-1.4.3-win", "Win64", "flac.exe"
            )
        else:
            flac_command = path.join(
                file_path, "utils", "flac-1.4.3-win", "Win32", "flac.exe"
            )
    else:
        flac_command = "flac"

    if not path.exists(args.path):
        raise FileNotFoundError(f"The path '{args.path}' does not exist.")

    flac_files = collect_files(args.path, ".flac")

    if len(flac_files) == 0:
        raise FileNotFoundError(f"No FLAC files found in '{args.path}'.")

    log_filename = collect_files(args.path, ".log")

    if len(log_filename) == 0:
        raise FileNotFoundError(f"No log files found in '{args.path}'.")
    elif len(log_filename) > 1:
        print("Multiple log files were found:")
        for i, file in enumerate(log_filename):
            print(f"{i}. {file}")
        choice = -1
        while choice < 0:
            try:
                choice = int(input("Select the log file (-1 to exit): "))
            except ValueError:
                print("Invalid choice.")
                choice = -1
            if choice == -1:
                _exit(0)
            elif choice < 0 or choice >= len(log_filename):
                print("Invalid choice.")
                choice = -1
        log_filename = log_filename[choice]
    else:
        log_filename = log_filename[0]

    verify_files(args.path, flac_files, log_filename, flac_command)


def download_flac():
    """
    Downloads the FLAC decoder for Windows and extracts it to the utils folder.
    """

    print("Windows detected. The FLAC decoder was not found. Downloading it...")
    makedirs(path.join(file_path, "utils"), exist_ok=True)

    url = "https://ftp.osuosl.org/pub/xiph/releases/flac/flac-1.4.3-win.zip"
    file_name = url.split("/")[-1]
    u = urllib.request.urlopen(url)
    with open(file_name, "wb") as f:
        meta = u.info()
        file_size = int(meta.get_all("Content-Length")[0])
        print(f"Downloading: {file_name}")
        print(f"Bytes: {file_size}")
        file_size_dl = 0
        block_size = 8192
        start_time = time.time()
        while True:
            buffer = u.read(block_size)
            if not buffer:
                break
            file_size_dl += len(buffer)
            f.write(buffer)
            status = (
                f"\r{file_size_dl:10d}  [{(file_size_dl * 100. / file_size):3.2f}%]"
            )
            status += f"  Speed: {((file_size_dl / 1024**2) / (time.time() - start_time)):.2f} MB/s"
            sys.stdout.write(status)
            sys.stdout.flush()

    with zipfile.ZipFile(file_name, "r") as zip_ref:
        zip_ref.extractall(path.join(file_path, "utils"))
    remove(file_name)


def collect_files(directory, extension):
    """
    Retrieve all files in a directory with a specific extension.
    """

    return [file for file in listdir(directory) if file.endswith(extension)]


def get_file_crc(album_path, file, flac_command):
    """
    Get the CRC of a FLAC file:
    1. Decode the FLAC file to a raw file
    2. Calculate the CRC of the raw file
    3. Delete the raw file
    4. Return the CRC
    """

    run(
        [
            flac_command,
            "-d",
            "--totally-silent",
            "--force-raw-format",
            "--endian=little",
            "--sign=signed",
            path.join(album_path, file),
        ]
    )

    to_return = 0

    with open(path.join(album_path, file.split(".")[0] + ".raw"), "rb") as raw_file:
        raw_data = raw_file.read()
        crc = crc32(raw_data)
        to_return = hex(crc & 0xFFFFFFFF)[2:]

    remove(path.join(album_path, file.split(".")[0] + ".raw"))

    return to_return


def verify_files(album_path, flac_files, log_filename, flac_command):
    """
    Verify the integrity of the FLAC files.
    """

    crc_dict = {}
    with open(path.join(album_path, log_filename), "rb") as raw:
        encoding = chardet.detect(raw.read())["encoding"]
    
    with open(path.join(album_path, log_filename), "r", encoding=encoding) as log_file:
        log_lines = log_file.readlines()
        i = 1
        for line in log_lines:
            if "Copy CRC" in line:
                crc_dict[i] = {
                    "file": "",
                    "copy_crc": line.split("Copy CRC ")[1].split("\n")[0].upper(),
                    "verified_crc": "",
                    "status": "",
                }
                i += 1

    if len(crc_dict) != len(flac_files):
        if len(crc_dict) == 0:
            raise ValueError("No CRCs found in the log file.")
        else:
            raise ValueError(
                "The number of FLAC files does not match the number of CRCs in the log file."
            )

    general_status = "OK"
    for file in tqdm(flac_files, desc="Verifying files"):
        flac_file = FLAC(path.join(album_path, file))
        track_number = int(flac_file["TRACKNUMBER"][0].split("/")[0]) if len(flac_files) > 1 else 1
        verified_crc = get_file_crc(album_path, file, flac_command).upper().zfill(8)
        crc_dict[track_number].update(
            {
                "file": file,
                "verified_crc": verified_crc,
                "status": "OK"
                if crc_dict[track_number]["copy_crc"] == verified_crc
                else "FAILED",
            }
        )

        if crc_dict[track_number]["status"] == "FAILED":
            general_status = "FAILED"

    print("\n")
    to_print = (
        f"CRChecker v0.0.2\n\nFiles verified on {time.strftime('%d/%m/%Y %H:%M:%S')}\n\n"
        f"Status: {general_status}\n\n{'-'*50}\n\n"
    )
    for key, value in crc_dict.items():
        to_print += f"Track {key}: {value['file']}\n"
        to_print += (
            f"Copy CRC: {value['copy_crc']} | "
            f"Verified CRC: {value['verified_crc']} | "
            f"Status: {value['status']}\n"
        )
        to_print += "\n\n"
    to_print = to_print.strip()
    print(to_print)

    if args.save:
        with open(
            path.join(album_path, "crchecker.log"), "w", encoding="ANSI"
        ) as verification_log:
            verification_log.write(to_print)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify the integrity of FLAC files.")
    parser.add_argument(
        "-p",
        "--path",
        type=str,
        help="Path to the FLAC files and extraction log.",
        required=True,
    )
    parser.add_argument(
        "-s",
        "--save",
        action="store_true",
        default=False,
        help="Save the verification log.",
    )

    args = parser.parse_args()

    main(args)
