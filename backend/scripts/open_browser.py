"""Used by start.bat: open the app in the browser once the server answers."""
import time
import urllib.error
import urllib.request
import webbrowser

URL = "http://localhost:8000"


def main() -> None:
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{URL}/api/health", timeout=2)
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
            continue
        webbrowser.open(URL)
        return
    print(f"The server did not start. Check the messages above, then open {URL} yourself.")


if __name__ == "__main__":
    main()
