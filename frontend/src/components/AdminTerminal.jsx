import React, { useState, useEffect, useRef } from 'react';
import { Terminal, ChevronDown, ChevronUp, Wifi, WifiOff } from 'lucide-react';

/**
 * AdminTerminal — streams real-time backend logs via WebSocket.
 *
 * Props:
 *   jobId   (string) — the Celery job ID to subscribe to
 *   token   (string) — admin JWT token, sent as ?token= query param
 *   apiUrl  (string) — base API URL (http:// or https://)
 *
 * Security: only rendered in Dashboard when isLoggedIn && terminalJobId.
 * The backend also enforces admin-only on the WebSocket endpoint.
 */
const AdminTerminal = ({ jobId, token, apiUrl }) => {
    const [isOpen, setIsOpen] = useState(true);
    const [logs, setLogs] = useState([]);
    const [connected, setConnected] = useState(false);
    const [done, setDone] = useState(false);
    const scrollRef = useRef(null);
    const wsRef = useRef(null);
    const reconnectTimerRef = useRef(null);
    const attemptsRef = useRef(0);
    const MAX_RECONNECT = 5;

    const buildWsUrl = () => {
        if (apiUrl.startsWith('http://') || apiUrl.startsWith('https://')) {
            // Dev: full URL pointing directly at uvicorn — swap protocol, no /api prefix
            const base = apiUrl
                .replace(/^http:\/\//, 'ws://')
                .replace(/^https:\/\//, 'wss://');
            return `${base}/ws/terminal/${jobId}?token=${encodeURIComponent(token)}`;
        } else {
            // Production: relative path like "/api" — derive host from window.location
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const base = `${protocol}//${window.location.host}${apiUrl}`;
            return `${base}/ws/terminal/${jobId}?token=${encodeURIComponent(token)}`;
        }
    };

    const connect = () => {
        if (!jobId || !token) return;
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

        const ws = new WebSocket(buildWsUrl());
        wsRef.current = ws;

        ws.onopen = () => {
            setConnected(true);
            attemptsRef.current = 0;
            setLogs(prev => [...prev, { type: 'system', message: '🔌 Terminal connected.' }]);
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'log') {
                    setLogs(prev => [...prev, { type: 'log', message: data.message, ts: data.ts }]);
                } else if (data.type === 'done') {
                    setDone(true);
                    setConnected(false);
                    setLogs(prev => [...prev, { type: 'system', message: '✅ Analysis complete.' }]);
                    ws.close();
                }
            } catch {
                // Plain text fallback
                setLogs(prev => [...prev, { type: 'log', message: event.data }]);
            }
        };

        ws.onerror = () => {
            setConnected(false);
        };

        ws.onclose = (event) => {
            setConnected(false);
            // 4001 = invalid token, 4003 = not admin — don't reconnect
            if (event.code === 4001 || event.code === 4003 || done) return;

            if (attemptsRef.current < MAX_RECONNECT) {
                attemptsRef.current += 1;
                setLogs(prev => [
                    ...prev,
                    { type: 'system', message: `📡 Reconnecting… (attempt ${attemptsRef.current}/${MAX_RECONNECT})` },
                ]);
                reconnectTimerRef.current = setTimeout(connect, 2000);
            } else {
                setLogs(prev => [...prev, { type: 'system', message: '⚠️ Could not reconnect to terminal.' }]);
            }
        };
    };

    useEffect(() => {
        setLogs([]);
        setDone(false);
        attemptsRef.current = 0;
        connect();

        return () => {
            clearTimeout(reconnectTimerRef.current);
            if (wsRef.current) {
                wsRef.current.onclose = null; // prevent reconnect on unmount
                wsRef.current.close();
            }
        };
    }, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps

    // Auto-scroll to bottom on new log lines
    useEffect(() => {
        if (isOpen && scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [logs, isOpen]);

    return (
        <div className="rounded-lg border border-green-700 bg-black overflow-hidden font-mono text-xs shadow-lg">
            {/* Header bar */}
            <div
                className="flex items-center justify-between px-3 py-2 bg-gray-900 border-b border-green-700 cursor-pointer select-none"
                onClick={() => setIsOpen(o => !o)}
            >
                <div className="flex items-center gap-2 text-green-400">
                    <Terminal className="w-3.5 h-3.5" />
                    <span className="font-semibold tracking-wide">Admin Terminal</span>
                    <span className="text-gray-500 text-[10px]">job:{jobId?.slice(0, 8)}…</span>
                </div>
                <div className="flex items-center gap-2">
                    {connected ? (
                        <span className="flex items-center gap-1 text-green-400">
                            <Wifi className="w-3 h-3" /> <span className="text-[10px]">LIVE</span>
                        </span>
                    ) : done ? (
                        <span className="text-green-600 text-[10px]">DONE</span>
                    ) : (
                        <span className="flex items-center gap-1 text-yellow-500">
                            <WifiOff className="w-3 h-3" /> <span className="text-[10px]">CONNECTING</span>
                        </span>
                    )}
                    {isOpen
                        ? <ChevronUp className="w-3.5 h-3.5 text-green-600" />
                        : <ChevronDown className="w-3.5 h-3.5 text-green-600" />
                    }
                </div>
            </div>

            {/* Log area */}
            {isOpen && (
                <div
                    ref={scrollRef}
                    className="h-56 overflow-y-auto p-3 space-y-0.5"
                    style={{ backgroundColor: '#0a0a0a' }}
                >
                    {logs.length === 0 && (
                        <p className="text-green-800 animate-pulse">Waiting for backend logs…</p>
                    )}
                    {logs.map((entry, i) => (
                        <div
                            key={i}
                            className={
                                entry.type === 'system'
                                    ? 'text-green-700'
                                    : 'text-green-400'
                            }
                        >
                            {entry.type === 'log' && entry.ts && (
                                <span className="text-green-800 mr-2">
                                    {new Date(entry.ts).toLocaleTimeString()}
                                </span>
                            )}
                            {entry.message}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default AdminTerminal;
