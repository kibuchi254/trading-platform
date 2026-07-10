/**
 * ATLAS Trading Platform — MT5 WebSocket Bridge DLL
 *
 * Implements a lightweight Windows WinHTTP-based WebSocket client.
 * Designed to compile to a 64-bit DLL (atlas_bridge.dll) for use in MetaTrader 5.
 */

#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif

#include <windows.h>
#include <winhttp.h>
#include <string>
#include <vector>
#include <map>
#include <mutex>
#include <sstream>

#pragma comment(lib, "winhttp.lib")
#pragma comment(lib, "ws2_32.lib")

#define DLLEXPORT extern "C" __declspec(dllexport)

struct WsSession {
    HINTERNET hSession = NULL;
    HINTERNET hConnect = NULL;
    HINTERNET hRequest = NULL;
    HINTERNET hWebSocket = NULL;
    bool isOpen = false;
    std::wstring lastReceivedMessage;
};

static std::map<int, WsSession*> g_sessions;
static std::mutex g_mutex;
static int g_nextHandle = 1;

// Helper to parse ws:// or wss:// URLs
bool ParseUrl(const std::wstring& url, std::wstring& host, int& port, std::wstring& path, bool& isSecure) {
    URL_COMPONENTS urlComp = { 0 };
    urlComp.dwStructSize = sizeof(urlComp);
    
    // Allocate buffer for host and path
    std::vector<wchar_t> hostBuf(url.length() + 1);
    std::vector<wchar_t> pathBuf(url.length() + 1);
    
    urlComp.lpszHostName = hostBuf.data();
    urlComp.dwHostNameLength = (DWORD)hostBuf.size();
    urlComp.lpszUrlPath = pathBuf.data();
    urlComp.dwUrlPathLength = (DWORD)pathBuf.size();
    
    // Convert ws:// to http:// and wss:// to https:// because WinHttpCrackUrl expects HTTP schemes
    std::wstring parsedUrl = url;
    if (url.rfind(L"ws://", 0) == 0) {
        parsedUrl = L"http://" + url.substr(5);
        isSecure = false;
    } else if (url.rfind(L"wss://", 0) == 0) {
        parsedUrl = L"https://" + url.substr(6);
        isSecure = true;
    } else {
        return false;
    }

    if (!WinHttpCrackUrl(parsedUrl.c_str(), 0, 0, &urlComp)) {
        return false;
    }

    host = urlComp.lpszHostName;
    port = urlComp.nPort;
    path = urlComp.lpszUrlPath;
    
    if (port == 0) {
        port = isSecure ? 443 : 80;
    }

    return true;
}

// Connect to WebSocket server
DLLEXPORT int ws_connect(const wchar_t* url_str) {
    if (!url_str) return -1;

    std::wstring url(url_str);
    std::wstring host, path;
    int port = 0;
    bool isSecure = false;

    if (!ParseUrl(url, host, port, path, isSecure)) {
        return -2;
    }

    WsSession* session = new WsSession();

    // 1. Open WinHttp session
    session->hSession = WinHttpOpen(L"ATLAS MT5 Bridge Client/1.0",
                                   WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                                   WINHTTP_NO_PROXY_NAME,
                                   WINHTTP_NO_PROXY_BYPASS, 0);
    if (!session->hSession) {
        delete session;
        return -3;
    }

    // 2. Connect to Host
    session->hConnect = WinHttpConnect(session->hSession, host.c_str(), (INTERNET_PORT)port, 0);
    if (!session->hConnect) {
        WinHttpCloseHandle(session->hSession);
        delete session;
        return -4;
    }

    // 3. Open HTTP Request
    DWORD flags = isSecure ? WINHTTP_FLAG_SECURE : 0;
    session->hRequest = WinHttpOpenRequest(session->hConnect, L"GET", path.c_str(),
                                          NULL, WINHTTP_NO_REFERER,
                                          WINHTTP_DEFAULT_ACCEPT_TYPES, flags);
    if (!session->hRequest) {
        WinHttpCloseHandle(session->hConnect);
        WinHttpCloseHandle(session->hSession);
        delete session;
        return -5;
    }

    // 4. Request WebSocket Upgrade
    if (!WinHttpSetOption(session->hRequest, WINHTTP_OPTION_UPGRADE_TO_WEBSOCKET, NULL, 0)) {
        WinHttpCloseHandle(session->hRequest);
        WinHttpCloseHandle(session->hConnect);
        WinHttpCloseHandle(session->hSession);
        delete session;
        return -6;
    }

    // 5. Send Request
    if (!WinHttpSendRequest(session->hRequest, WINHTTP_NO_ADDITIONAL_HEADERS, 0,
                            WINHTTP_NO_REQUEST_DATA, 0, 0, 0)) {
        WinHttpCloseHandle(session->hRequest);
        WinHttpCloseHandle(session->hConnect);
        WinHttpCloseHandle(session->hSession);
        delete session;
        return -7;
    }

    // 6. Receive Response
    if (!WinHttpReceiveResponse(session->hRequest, NULL)) {
        WinHttpCloseHandle(session->hRequest);
        WinHttpCloseHandle(session->hConnect);
        WinHttpCloseHandle(session->hSession);
        delete session;
        return -8;
    }

    // 7. Complete WebSocket Upgrade
    session->hWebSocket = WinHttpWebSocketCompleteUpgrade(session->hRequest, NULL);
    if (!session->hWebSocket) {
        WinHttpCloseHandle(session->hRequest);
        WinHttpCloseHandle(session->hConnect);
        WinHttpCloseHandle(session->hSession);
        delete session;
        return -9;
    }

    // We no longer need the request handle after upgrading
    WinHttpCloseHandle(session->hRequest);
    session->hRequest = NULL;

    session->isOpen = true;

    // Save session in registry
    std::lock_guard<std::mutex> lock(g_mutex);
    int handle = g_nextHandle++;
    g_sessions[handle] = session;

    return handle;
}

// Close WebSocket connection
DLLEXPORT void ws_close(int handle) {
    std::lock_guard<std::mutex> lock(g_mutex);
    auto it = g_sessions.find(handle);
    if (it != g_sessions.end()) {
        WsSession* session = it->second;
        if (session->hWebSocket) {
            if (session->isOpen) {
                WinHttpWebSocketClose(session->hWebSocket, WINHTTP_WEB_SOCKET_SUCCESS_CLOSE_STATUS, NULL, 0);
            }
            WinHttpCloseHandle(session->hWebSocket);
        }
        if (session->hConnect) WinHttpCloseHandle(session->hConnect);
        if (session->hSession) WinHttpCloseHandle(session->hSession);
        delete session;
        g_sessions.erase(it);
    }
}

// Send a message over WebSocket
DLLEXPORT int ws_send(int handle, const wchar_t* msg_str) {
    if (!msg_str) return -1;

    WsSession* session = NULL;
    {
        std::lock_guard<std::mutex> lock(g_mutex);
        auto it = g_sessions.find(handle);
        if (it != g_sessions.end()) {
            session = it->second;
        }
    }

    if (!session || !session->isOpen) return -2;

    std::wstring msg(msg_str);
    // Convert wide string to UTF-8
    int utf8_len = WideCharToMultiByte(CP_UTF8, 0, msg.c_str(), -1, NULL, 0, NULL, NULL);
    if (utf8_len <= 0) return -3;

    std::vector<char> utf8_buf(utf8_len);
    WideCharToMultiByte(CP_UTF8, 0, msg.c_str(), -1, utf8_buf.data(), utf8_len, NULL, NULL);

    // Send the UTF-8 payload (excluding null terminator)
    DWORD dwError = WinHttpWebSocketSend(session->hWebSocket, 
                                         WINHTTP_WEB_SOCKET_UTF8_MESSAGE_BUFFER_TYPE, 
                                         (PVOID)utf8_buf.data(), 
                                         utf8_len - 1);
    if (dwError != ERROR_SUCCESS) {
        session->isOpen = false;
        return -4;
    }

    return 1; // Success
}

// Check if WebSocket is open
DLLEXPORT bool ws_is_open(int handle) {
    std::lock_guard<std::mutex> lock(g_mutex);
    auto it = g_sessions.find(handle);
    if (it != g_sessions.end()) {
        return it->second->isOpen;
    }
    return false;
}

// Receive message with timeout
// Returns const wchar_t* because MQL5 maps this directly to MQL5 string.
// The MQL5 environment copies returned strings immediately, so returning a pointer
// to a session-owned persistent buffer is thread-safe and memory-safe.
DLLEXPORT const wchar_t* ws_recv(int handle, int timeout_ms) {
    WsSession* session = NULL;
    {
        std::lock_guard<std::mutex> lock(g_mutex);
        auto it = g_sessions.find(handle);
        if (it != g_sessions.end()) {
            session = it->second;
        }
    }

    if (!session || !session->isOpen) return L"";

    // Set read timeout
    DWORD dwTimeout = (DWORD)timeout_ms;
    WinHttpSetOption(session->hWebSocket, WINHTTP_OPTION_RECEIVE_TIMEOUT, &dwTimeout, sizeof(dwTimeout));

    std::vector<char> buffer;
    const DWORD chunk_size = 4096;
    std::vector<char> chunk(chunk_size);
    
    WINHTTP_WEB_SOCKET_BUFFER_TYPE bufferType;
    DWORD bytesRead = 0;
    DWORD dwError = ERROR_SUCCESS;

    do {
        dwError = WinHttpWebSocketReceive(session->hWebSocket, 
                                          chunk.data(), 
                                          chunk_size, 
                                          &bytesRead, 
                                          &bufferType);
        if (dwError != ERROR_SUCCESS) {
            if (dwError != ERROR_TIMEOUT) {
                session->isOpen = false;
            }
            return L""; // Timeout or connection error
        }

        if (bytesRead > 0) {
            buffer.insert(buffer.end(), chunk.data(), chunk.data() + bytesRead);
        }

    } while (bufferType == WINHTTP_WEB_SOCKET_UTF8_FRAGMENT_BUFFER_TYPE ||
             bufferType == WINHTTP_WEB_SOCKET_BINARY_FRAGMENT_BUFFER_TYPE);

    if (buffer.empty()) {
        if (bufferType == WINHTTP_WEB_SOCKET_CLOSE_BUFFER_TYPE) {
            session->isOpen = false;
        }
        return L"";
    }

    // Convert UTF-8 back to WideChar (wstring)
    buffer.push_back('\0'); // Ensure null terminator for conversion
    int wlen = MultiByteToWideChar(CP_UTF8, 0, buffer.data(), -1, NULL, 0);
    if (wlen <= 0) return L"";

    std::vector<wchar_t> wbuf(wlen);
    MultiByteToWideChar(CP_UTF8, 0, buffer.data(), -1, wbuf.data(), wlen);

    session->lastReceivedMessage = wbuf.data();
    return session->lastReceivedMessage.c_str();
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call, LPVOID lpReserved) {
    switch (ul_reason_for_call) {
    case DLL_PROCESS_ATTACH:
        break;
    case DLL_PROCESS_DETACH:
        // Cleanup all sessions on unload
        {
            std::lock_guard<std::mutex> lock(g_mutex);
            for (auto& pair : g_sessions) {
                WsSession* session = pair.second;
                if (session->hWebSocket) {
                    WinHttpWebSocketClose(session->hWebSocket, WINHTTP_WEB_SOCKET_SUCCESS_CLOSE_STATUS, NULL, 0);
                    WinHttpCloseHandle(session->hWebSocket);
                }
                if (session->hConnect) WinHttpCloseHandle(session->hConnect);
                if (session->hSession) WinHttpCloseHandle(session->hSession);
                delete session;
            }
            g_sessions.clear();
        }
        break;
    }
    return TRUE;
}
