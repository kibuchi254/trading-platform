# ATLAS MT5 WebSocket Bridge DLL

This directory contains the C++ source code and compilation instructions for `atlas_bridge.dll`. 
The DLL implements a lightweight, native Windows WinHTTP-based WebSocket client that allows MetaTrader 5 (running on Windows or Wine on Linux) to communicate with the ATLAS Bridge server.

Using native WinHTTP ensures:
1. **No External Dependencies**: No OpenSSL, Boost, or other heavy dependencies.
2. **Native TLS/SSL Support**: Automatically supports `wss://` secure connections using Windows/Wine certificate stores.
3. **Small Binary Size**: Typically under 50 KB.

---

## Quick Start (Option A - Pre-compiled Binaries)

For convenience, if you do not want to compile the DLL from source:
1. Download a pre-compiled version of the MT5 WebSocket DLL from the repository release page or a trusted community source (e.g., [lws2mql](https://github.com/nicowillis/mt5-websocket) or standard `easywsclient` DLL wrappers).
2. Rename the downloaded DLL to `atlas_bridge.dll`.
3. Move `atlas_bridge.dll` to your MT5 terminal's `MQL5/Libraries/` folder:
   - **Local Windows**: `%APPDATA%/MetaQuotes/Terminal/<InstanceID>/MQL5/Libraries/`
   - **Wine (Linux Host)**: `/opt/atlas/mt5/MQL5/Libraries/` (or the corresponding Wine drive `C:\` location).

---

## Compiling from Source

If you prefer to compile it yourself, you can do so on Windows or cross-compile it directly on the Linux VPS using MinGW.

### Method 1: Cross-compiling on Linux (Wine-friendly)

If you are running MT5 on Wine on a Ubuntu/Debian server, you can compile the DLL using the MinGW cross-compiler:

```bash
# 1. Install MinGW cross-compiler
sudo apt-get update
sudo apt-get install -y g++-mingw-w64-x86-64

# 2. Compile the DLL (64-bit target for MT5)
x86_64-w64-mingw32-g++ -shared -o atlas_bridge.dll atlas_bridge.cpp -lwinhttp -lws2_32 -static
```

### Method 2: Compiling on Windows

Using **MSVC (Visual Studio Developer PowerShell)**:

```powershell
cl.exe /LD /O2 /EHsc atlas_bridge.cpp /link winhttp.lib ws2_32.lib /OUT:atlas_bridge.dll
```

Using **MinGW (GCC) on Windows**:

```powershell
g++ -shared -o atlas_bridge.dll atlas_bridge.cpp -lwinhttp -lws2_32 -static
```

---

## MQL5 Imports

The DLL functions map exactly to the imports declared in [BridgeEA.mq5](file:///c:/Projects/trading-platform/mql5/BridgeEA.mq5):

```mql5
#import "atlas_bridge.dll"
   int      ws_connect(string url);
   void     ws_close(int handle);
   int      ws_send(int handle, string msg);
   string   ws_recv(int handle, int timeout_ms);
   bool     ws_is_open(int handle);
#import
```
