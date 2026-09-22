# Start the local web app

## macOS Terminal

1. Open **Terminal**.
2. Move into the repository:

```bash
cd "/Users/finn/Desktop/panel press"
```

3. Make the launcher executable once:

```bash
chmod +x start.sh
```

4. Start the app:

```bash
./start.sh
```

If an older local instance is already using port 8080, the script stops that user-owned process and starts a fresh instance.

5. Open [http://127.0.0.1:8080/](http://127.0.0.1:8080/) in your browser.

Keep the Terminal window open while using the app. Press `Ctrl+C` in that window to stop the server.

## Use another port

If port 8080 is already in use:

```bash
PORT=8081 ./start.sh
```

Then open [http://127.0.0.1:8081/](http://127.0.0.1:8081/).

## Windows

1. Install Python 3 and make sure `python` works in Command Prompt:

```bat
python --version
```

2. Double-click `start.bat`, or run it from Command Prompt:

```bat
cd /d "C:\path\to\panel press"
start.bat
```

3. Open [http://127.0.0.1:8080/](http://127.0.0.1:8080/) in your browser.

If port 8080 is already in use, choose another port before starting:

```bat
set PORT=8081
start.bat
```

To use a Python executable that is not on PATH:

```bat
set PYTHON_BIN=C:\path\to\python.exe
start.bat
```

## If Python is not found

Check the installed command:

```bash
python3 --version
```

Or provide another Python executable:

```bash
PYTHON_BIN=/path/to/python3 ./start.sh
```
